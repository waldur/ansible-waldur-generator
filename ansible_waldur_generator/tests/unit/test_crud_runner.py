import pytest
from unittest.mock import patch

from ansible_waldur_generator.plugins.crud.runner import CrudRunner


@pytest.fixture
def mock_crud_runner_context():
    """
    A pytest fixture that provides a realistic, mocked context dictionary for a
    full-featured CRUD module. This context simulates the configuration for a
    'security group' resource, which is a nested resource under a 'tenant' and
    supports both simple field updates ('description') and a complex action update
    ('set_rules'). This complexity allows us to test all features of the CrudRunner.
    """
    context = {
        "resource_type": "security group",
        # --- API Paths ---
        "check_url": "/api/security-groups/",
        "list_path": "/api/security-groups/",
        # Note: A nested creation path
        "create_path": "/api/tenants/{uuid}/security_groups/",
        "destroy_path": "/api/security-groups/{uuid}/",
        "update_path": "/api/security-groups/{uuid}/",
        # --- Mappings and Configurations ---
        "model_param_names": ["name", "description", "rules"],
        "update_fields": ["description"],
        "update_actions": {
            "set_rules": {
                "path": "/api/security-groups/{uuid}/set_rules/",
                "param": "rules",
                "compare_key": "rules",  # For idempotency, compare against the 'rules' key on the resource
                "wrap_in_object": True,  # The API expects {"rules": [...]}
                "idempotency_keys": [
                    "protocol",
                    "from_port",
                    "to_port",
                    "cidr",
                ],  # Keys to uniquely identify a rule
            }
        },
        # Defines how to map URL placeholders to Ansible parameters for nested creation.
        "path_param_maps": {"create": {"uuid": "tenant"}},
        # Defines how to resolve the 'tenant' parameter from a name/UUID to a URL.
        "resolvers": {
            "tenant": {
                "url": "/api/tenants/",
                "error_message": "Tenant '{value}' not found.",
            },
        },
    }
    return context


class TestCrudRunner:
    """
    A comprehensive test suite for the CrudRunner's "plan-and-execute" logic.
    Each test validates that the runner correctly builds a change plan and,
    when not in check mode, executes it to produce the correct final state and diff.
    """

    # ==========================================================================
    # == CREATE SCENARIOS
    # ==========================================================================

    @patch("ansible_waldur_generator.plugins.crud.runner.CrudRunner.send_request")
    def test_create_nested_resource_successfully(
        self, mock_send_request, mock_ansible_module, mock_crud_runner_context
    ):
        """
        Tests the successful creation of a new, nested resource.

        This test is critical as it validates:
        1.  The runner correctly identifies that the resource does not exist.
        2.  It resolves the parent resource ('tenant') to its URL to extract the UUID.
        3.  It correctly assembles the payload and path parameters.
        4.  It builds a `CreateCommand` and executes it.
        5.  The final `exit_json` call contains the correct state, diff, and `changed=True`.
        """
        # --- ARRANGE ---
        mock_ansible_module.params = {
            "state": "present",
            "name": "new-web-sg",
            "description": "Allow web traffic",
            "tenant": "Cloud Tenant",  # The parent resource identifier
        }

        # The expected final state of the resource after creation.
        new_resource = {
            "name": "new-web-sg",
            "uuid": "new-sg-uuid",
            "description": "Allow web traffic",
        }
        # The expected response when resolving the parent 'tenant'.
        tenant_url_response = (
            [{"url": "http://api.com/api/tenants/tenant-uuid/"}],
            200,
        )

        # Define the exact sequence of mocked API calls for the entire run.
        mock_send_request.side_effect = [
            # 1. `check_existence`: The resource is not found.
            ([], 200),
            # 2. `build_change_plan`: The resolver for the 'tenant' path parameter is called.
            tenant_url_response,
            # 3. `execute_change_plan`: The `CreateCommand.execute()` method is called.
            (new_resource, 201),
        ]

        # --- ACT ---
        runner = CrudRunner(mock_ansible_module, mock_crud_runner_context)
        runner.run()

        # --- ASSERT ---
        # 1. Verify that the create API call was made to the correct nested endpoint.
        mock_send_request.assert_any_call(
            "POST",
            "/api/tenants/{uuid}/security_groups/",
            data={"name": "new-web-sg", "description": "Allow web traffic"},
            path_params={"uuid": "tenant-uuid"},
        )

        # 2. Define the expected diff that the plan should have generated.
        expected_diff = [
            {
                "state": "Resource will be created.",
                "new_attributes": {
                    "name": "new-web-sg",
                    "description": "Allow web traffic",
                },
            }
        ]

        # 3. Assert the final state of the module.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=new_resource, diff=expected_diff
        )
        mock_ansible_module.fail_json.assert_not_called()

    # ==========================================================================
    # == NO-OP SCENARIOS
    # ==========================================================================

    @patch("ansible_waldur_generator.plugins.crud.runner.CrudRunner.send_request")
    def test_resource_exists_and_is_unchanged(
        self, mock_send_request, mock_ansible_module, mock_crud_runner_context
    ):
        """
        Tests idempotency: if a resource exists and its configuration matches the
        desired state, no changes should be planned or executed.
        """
        # --- ARRANGE ---
        mock_ansible_module.params = {
            "state": "present",
            "name": "existing-sg",
            "description": "current description",  # Value matches the existing resource
            "rules": [
                {"protocol": "tcp", "from_port": 22}
            ],  # Value matches the existing resource
        }

        # The current state of the resource as returned by the API.
        existing_resource = {
            "name": "existing-sg",
            "uuid": "existing-sg-uuid",
            "description": "current description",
            "rules": [{"protocol": "tcp", "from_port": 22}],
        }
        # Only one API call is needed: the initial existence check.
        mock_send_request.return_value = ([existing_resource], 200)

        # --- ACT ---
        runner = CrudRunner(mock_ansible_module, mock_crud_runner_context)
        runner.run()

        # --- ASSERT ---
        # The plan should be empty, resulting in `changed=False` and an empty diff.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=existing_resource, diff=[]
        )
        mock_ansible_module.fail_json.assert_not_called()
        # Crucially, assert that only the initial GET request was made.
        mock_send_request.assert_called_once()

    # ==========================================================================
    # == UPDATE SCENARIOS
    # ==========================================================================

    @patch("ansible_waldur_generator.plugins.crud.runner.CrudRunner.send_request")
    def test_update_simple_and_action_fields_together(
        self, mock_send_request, mock_ansible_module, mock_crud_runner_context
    ):
        """
        Tests the most complex update scenario: changing both a simple field
        (triggering a PATCH) and a complex action field (triggering a POST) in a
        single task. This validates that the runner can correctly plan and execute
        multiple, different types of commands.
        """
        # --- ARRANGE ---
        mock_ansible_module.params = {
            "state": "present",
            "name": "sg-to-update",
            "description": "A new, better description",
            "rules": [
                {
                    "protocol": "tcp",
                    "from_port": 443,
                    "to_port": 443,
                    "cidr": "0.0.0.0/0",
                }
            ],
        }

        existing_resource = {
            "name": "sg-to-update",
            "uuid": "sg-uuid-123",
            "description": "old description",
            "rules": [],
        }

        patched_resource = {
            **existing_resource,
            "description": "A new, better description",
        }

        # **FIX**: This is the key change. The final re-fetch of the resource
        # must return the complete, final state of the object, including
        # the results of ALL updates (the patched description and the new rules).
        final_resource_state = {
            **patched_resource,
            "rules": mock_ansible_module.params["rules"],
        }

        mock_send_request.side_effect = [
            (
                [existing_resource],
                200,
            ),  # 1. `check_existence` finds the initial resource.
            (
                patched_resource,
                200,
            ),  # 2. `UpdateCommand.execute()` returns the patched state.
            (None, 200),  # 3. `ActionCommand.execute()` returns no body.
            (
                [final_resource_state],
                200,
            ),  # 4. The re-fetch call now returns the complete final state.
        ]

        # --- ACT ---
        runner = CrudRunner(mock_ansible_module, mock_crud_runner_context)
        runner.run()

        # --- ASSERT ---
        expected_diff = [
            {
                "updated_attributes": [
                    {
                        "param": "description",
                        "old": "old description",
                        "new": "A new, better description",
                    }
                ]
            },
            {"action": "rules", "old": [], "new": mock_ansible_module.params["rules"]},
        ]

        # This assertion will now pass because the runner's `self.resource` will
        # be correctly updated to the `final_resource_state` by the final re-fetch.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=final_resource_state, diff=expected_diff
        )

    # ==========================================================================
    # == DELETE SCENARIOS
    # ==========================================================================

    @patch("ansible_waldur_generator.plugins.crud.runner.CrudRunner.send_request")
    def test_delete_existing_resource(
        self, mock_send_request, mock_ansible_module, mock_crud_runner_context
    ):
        """
        Tests the successful deletion of an existing resource.
        """
        # --- ARRANGE ---
        mock_ansible_module.params = {
            "state": "absent",
            "name": "sg-to-delete",
        }

        existing_resource = {"name": "sg-to-delete", "uuid": "sg-to-delete-uuid"}
        mock_send_request.side_effect = [
            # 1. `check_existence`: Finds the resource.
            ([existing_resource], 200),
            # 2. `execute_change_plan` -> `DeleteCommand.execute()`: The DELETE call.
            (None, 204),
        ]

        # --- ACT ---
        runner = CrudRunner(mock_ansible_module, mock_crud_runner_context)
        runner.run()

        # --- ASSERT ---
        expected_diff = [
            {"state": "Resource will be deleted.", "old_attributes": existing_resource}
        ]
        # After execution, the resource state is `None`.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=None, diff=expected_diff
        )

    @patch("ansible_waldur_generator.plugins.crud.runner.CrudRunner.send_request")
    def test_delete_non_existent_resource(
        self, mock_send_request, mock_ansible_module, mock_crud_runner_context
    ):
        """
        Tests idempotency for deletion: if a resource is already absent,
        no plan should be generated and no change should occur.
        """
        # --- ARRANGE ---
        mock_ansible_module.params = {"state": "absent", "name": "non-existent-sg"}
        mock_send_request.return_value = ([], 200)  # `check_existence` finds nothing.

        # --- ACT ---
        runner = CrudRunner(mock_ansible_module, mock_crud_runner_context)
        runner.run()

        # --- ASSERT ---
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=None, diff=[]
        )
        mock_send_request.assert_called_once()  # Only the existence check is made.

    # ==========================================================================
    # == CHECK MODE SCENARIOS
    # ==========================================================================

    @patch("ansible_waldur_generator.plugins.crud.runner.CrudRunner.send_request")
    def test_check_mode_predicts_creation(
        self, mock_send_request, mock_ansible_module, mock_crud_runner_context
    ):
        """
        Tests that check mode correctly predicts the creation of a resource and
        generates the appropriate diff without making any modifying API calls.
        """
        # --- ARRANGE ---
        mock_ansible_module.check_mode = True
        mock_ansible_module.params = {
            "state": "present",
            "name": "new-sg-check-mode",
            "tenant": "Cloud Tenant",
        }

        # Define the sequence of *read-only* calls needed for planning.
        mock_send_request.side_effect = [
            ([], 200),  # `check_existence` finds nothing.
            (
                [{"url": "http://api.com/api/tenants/tenant-uuid/"}],
                200,
            ),  # Resolver call.
        ]

        # --- ACT ---
        runner = CrudRunner(mock_ansible_module, mock_crud_runner_context)
        runner.run()

        # --- ASSERT ---
        expected_diff = [
            {
                "state": "Resource will be created.",
                "new_attributes": {"name": "new-sg-check-mode"},
            }
        ]
        # In check mode, `resource` is `None` because nothing was executed.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=None, diff=expected_diff
        )
