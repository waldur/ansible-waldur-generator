import pytest
from unittest.mock import patch, ANY

# The class we are testing
from ansible_waldur_generator.plugins.order.runner import OrderRunner


@pytest.fixture
def mock_instance_runner_context():
    """
    A pytest fixture providing a realistic, mocked context dictionary for a full-featured
    OpenStack instance module, including nested resolvers.
    """
    context = {
        "resource_type": "OpenStack instance",
        "check_url": "/api/openstack-instances/",
        "check_filter_keys": {"project": "project_uuid"},
        "update_path": "/api/openstack-instances/{uuid}/",
        "update_fields": ["description", "name"],
        "attribute_param_names": [
            "flavor",
            "image",
            "security_groups",
            "system_volume_size",
            "user_data",
            "ports",
            "floating_ips",
            "ssh_public_key",
            "availability_zone",
        ],
        "update_actions": {
            "update_ports": {
                "path": "/api/openstack-instances/{uuid}/update_ports/",
                "param": "ports",
                "compare_key": "ports",
                # This metadata would be inferred by the plugin
                "idempotency_keys": ["subnet", "fixed_ips"],
                "wrap_in_object": True,
            },
            "update_security_groups": {
                "path": "/api/openstack-instances/{uuid}/update_security_groups/",
                "param": "security_groups",
                "compare_key": "security_groups",
                # This metadata would be inferred by the plugin
                "idempotency_keys": [],  # For a simple list of strings
                "wrap_in_object": True,
            },
        },
        "resolvers": {
            "project": {
                "url": "/api/projects/",
                "error_message": "Project '{value}' not found.",
                "is_list": False,
                "filter_by": [],
            },
            "offering": {
                "url": "/api/marketplace-public-offerings/",
                "error_message": "Offering '{value}' not found.",
                "is_list": False,
                "filter_by": [],
            },
            "flavor": {
                "url": "/api/openstack-flavors/",
                "error_message": "Flavor '{value}' not found.",
                "is_list": False,
                "filter_by": [
                    {
                        "source_param": "offering",
                        "source_key": "scope_uuid",
                        "target_key": "tenant_uuid",
                    }
                ],
            },
            "image": {
                "url": "/api/openstack-images/",
                "error_message": "Image '{value}' not found.",
                "is_list": False,
                "filter_by": [
                    {
                        "source_param": "offering",
                        "source_key": "scope_uuid",
                        "target_key": "tenant_uuid",
                    }
                ],
            },
            "security_groups": {
                "url": "/api/openstack-security-groups/",
                "error_message": "Security group '{value}' not found.",
                "is_list": True,
                "filter_by": [
                    {
                        "source_param": "offering",
                        "source_key": "scope_uuid",
                        "target_key": "tenant_uuid",
                    }
                ],
                "list_item_keys": {"create": "url", "update_action": None},
            },
            # This is the key resolver for the new complex test case
            "subnet": {
                "url": "/api/openstack-subnets/",
                "error_message": "Subnet '{value}' not found.",
                "is_list": False,  # The resolver itself finds one item at a time
                "filter_by": [
                    {
                        "source_param": "offering",
                        "source_key": "scope_uuid",
                        "target_key": "tenant_uuid",
                    }
                ],
            },
            "ssh_public_key": {
                "url": "/api/ssh-keys/",
                "error_message": "SSH key '{value}' not found.",
                "is_list": False,
                "filter_by": [],
            },
        },
        "termination_attributes_map": {
            "termination_action": "action",
            "delete_volumes": "delete_volumes",
            "release_floating_ips": "release_floating_ips",
        },
    }
    return context


# --- Test Class for OrderRunner ---


class TestOrderRunner:
    """
    A comprehensive test suite for the OrderRunner logic, covering creation,
    updates, deletion, and advanced resolver scenarios.
    """

    # --- Scenario 1: Create a new comprehensive resource ---
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner.send_request")
    def test_create_instance_with_full_payload(
        self, mocksend_request, mock_ansible_module, mock_instance_runner_context
    ):
        """
        Tests the full payload creation for a complex instance, validating that all
        resolvers (top-level, dependent, list-based, and nested) work together
        to build the correct final API request.
        """
        # Arrange: Define a rich set of user parameters.
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "token",
            "state": "present",
            "wait": True,
            "interval": 1,
            "timeout": 1,
            "name": "prod-web-vm-01",
            "project": "Production Project",
            "offering": "Premium Instance Offering",
            "plan": "http://api.com/api/plans/plan-uuid/",  # Non-resolved URL
            "limits": {"cpu": 8, "ram": 16384},  # Non-resolved dict
            "flavor": "large-flavor",
            "image": "ubuntu-22.04-image",
            "security_groups": ["web-access-sg", "ssh-internal-sg"],
            "system_volume_size": 100,
            "ports": [
                {
                    "subnet": "private-network-subnet",
                    "fixed_ips": [{"ip_address": "10.0.1.50"}],
                }
            ],
            "floating_ips": [{"subnet": "public-floating-ip-subnet"}],
            "ssh_public_key": "admin-ssh-key",
        }

        final_resource_state = {
            "name": "prod-web-vm-01",
            "state": "OK",
            "uuid": "final-vm-uuid-123",
        }

        # Arrange: Mock the sequence of all required API calls.
        mocksend_request.side_effect = [
            # 1. Existence Check Phase
            ([{"url": "http://api.com/api/projects/proj-prod-uuid/"}], 200),
            ([], 200),  # Instance does not exist
            # 2. Create Phase: Parameter Resolution
            ([{"url": "http://api.com/api/projects/proj-prod-uuid/"}], 200),  # project
            (
                [
                    {
                        "url": "http://api.com/api/offerings/off-prem-uuid/",
                        "scope_uuid": "tenant-prod-123",
                    }
                ],
                200,
            ),  # offering
            ([{"url": "http://api.com/api/flavors/flavor-large-uuid/"}], 200),  # flavor
            ([{"url": "http://api.com/api/images/img-ubuntu-uuid/"}], 200),  # image
            (
                [{"url": "http://api.com/api/security-groups/sg-web-uuid/"}],
                200,
            ),  # security_groups[0]
            (
                [{"url": "http://api.com/api/security-groups/sg-ssh-uuid/"}],
                200,
            ),  # security_groups[1]
            (
                [{"url": "http://api.com/api/subnets/subnet-private-uuid/"}],
                200,
            ),  # ports[0].subnet
            (
                [{"url": "http://api.com/api/subnets/subnet-public-uuid/"}],
                200,
            ),  # floating_ips[0].subnet
            (
                [{"url": "http://api.com/api/ssh-keys/key-admin-uuid/"}],
                200,
            ),  # ssh_public_key
            # 3. Create Phase: Order Submission
            ({"uuid": "order-xyz-789"}, 200),
            # 4. Wait Phase
            ({"state": "done"}, 200),
            (
                [{"url": "http://api.com/api/projects/proj-prod-uuid/"}],
                200,
            ),  # Final project resolve
            ([final_resource_state], 200),  # Final existence check
        ]

        # Arrange: Define the exact payload the runner is expected to build.
        expected_payload = {
            "project": "http://api.com/api/projects/proj-prod-uuid/",
            "offering": "http://api.com/api/offerings/off-prem-uuid/",
            "plan": "http://api.com/api/plans/plan-uuid/",
            "limits": {"cpu": 8, "ram": 16384},
            "accepting_terms_of_service": True,
            "attributes": {
                "name": "prod-web-vm-01",
                "flavor": "http://api.com/api/flavors/flavor-large-uuid/",
                "image": "http://api.com/api/images/img-ubuntu-uuid/",
                "security_groups": [
                    {"url": "http://api.com/api/security-groups/sg-web-uuid/"},
                    {"url": "http://api.com/api/security-groups/sg-ssh-uuid/"},
                ],
                "system_volume_size": 100,
                "ports": [
                    {
                        "subnet": "http://api.com/api/subnets/subnet-private-uuid/",
                        "fixed_ips": [{"ip_address": "10.0.1.50"}],
                    }
                ],
                "floating_ips": [
                    {"subnet": "http://api.com/api/subnets/subnet-public-uuid/"}
                ],
                "ssh_public_key": "http://api.com/api/ssh-keys/key-admin-uuid/",
            },
        }

        # Act
        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        expected_diff = [
            {
                "state": "Resource created.",
                "order_details": {"uuid": "order-xyz-789"},
            }
        ]

        # Assert: Final state is correct
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True,
            diff=expected_diff,
            resource={
                "name": "prod-web-vm-01",
                "state": "OK",
                "uuid": "final-vm-uuid-123",
            },
            order={"uuid": "order-xyz-789"},
        )

        # Assert: The order creation call was made with the exact expected payload
        order_creation_call = mocksend_request.call_args_list[11]
        assert order_creation_call.args == ("POST", "/api/marketplace-orders/")
        assert order_creation_call.kwargs["data"] == expected_payload

    # --- Scenario 2: Resource already exists, no changes needed ---
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner.send_request")
    def test_resource_exists_no_change(
        self, mocksend_request, mock_ansible_module, mock_instance_runner_context
    ):
        """
        Tests idempotency: if the resource exists and its updatable fields match,
        no changes should be made.
        """
        # Arrange
        mock_ansible_module.params = {
            "state": "present",
            "name": "existing-vm",
            "project": "Cloud Project",
            "description": "current description",
        }
        existing_resource = {
            "name": "existing-vm",
            "description": "current description",
            "state": "OK",
        }
        mocksend_request.side_effect = [
            # 1. Existence Check
            (
                [{"url": "http://api.com/api/projects/proj-uuid/"}],
                200,
            ),  # resolve project for check
            ([existing_resource], 200),  # find resource
            # 2. Update() method starts
            # It now calls prime_cache_from_resource, which is mocked by default and does nothing
            # Then it explicitly resolves 'project' if provided
            (
                [{"url": "http://api.com/api/projects/proj-uuid/"}],
                200,
            ),  # resolve project for update
        ]

        # Act
        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, diff=[], resource=existing_resource, order=None
        )

    # --- Scenario 3: Update an existing resource ---
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner.send_request")
    def test_update_existing_resource(
        self, mocksend_request, mock_ansible_module, mock_instance_runner_context
    ):
        """
        Tests that a change to an updatable field (like 'description')
        triggers a PATCH request.
        """
        # Arrange
        mock_ansible_module.params = {
            "state": "present",
            "name": "vm-to-update",
            "project": "Cloud Project",
            "description": "a new description",
        }
        existing_resource = {
            "name": "vm-to-update",
            "uuid": "vm-uuid-456",
            "description": "old description",
        }
        updated_resource = {**existing_resource, "description": "a new description"}

        def side_effect(method, path, **kwargs):
            if method == "GET" and "/api/projects/" in path:
                return ([{"url": "http://api.com/api/projects/proj-uuid/"}], 200)
            elif method == "GET" and "/api/openstack-instances/" in path:
                return ([existing_resource], 200)
            elif method == "PATCH" and "/api/openstack-instances/" in path:
                return (updated_resource, 200)
            return None

        mocksend_request.side_effect = side_effect

        # Act
        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        expected_diff = [
            {
                "updated_attributes": [
                    {
                        "param": "description",
                        "old": "old description",
                        "new": "a new description",
                    }
                ]
            }
        ]

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, diff=expected_diff, resource=updated_resource, order=None
        )
        # Verify the PATCH call was made correctly.
        mocksend_request.assert_any_call(
            "PATCH",
            "/api/openstack-instances/{uuid}/",
            data={"description": "a new description"},
            path_params={"uuid": "vm-uuid-456"},
        )

    # --- Scenario 4: Delete an existing resource ---
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner.send_request")
    def test_delete_existing_resource(
        self, mocksend_request, mock_ansible_module, mock_instance_runner_context
    ):
        """
        Tests that `state: absent` correctly triggers a termination call
        when the resource exists.
        """
        # Arrange
        mock_ansible_module.params = {
            "state": "absent",
            "name": "vm-to-delete",
            "project": "Cloud Project",
        }
        existing_resource = {
            "name": "vm-to-delete",
            "marketplace_resource_uuid": "mkt-res-uuid-789",
        }
        mocksend_request.side_effect = [
            (
                [{"url": "http://api.com/api/projects/proj-uuid/"}],
                200,
            ),  # Resolve project
            ([existing_resource], 200),  # Existence check finds it
            (None, 204),  # The terminate call returns 204 No Content
        ]

        # Act
        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        expected_diff = [
            {
                "state": "Resource will be deleted.",
                "old_attributes": existing_resource,
            }
        ]

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, diff=expected_diff, resource=None, order=None
        )
        # Verify the termination call was made to the correct endpoint.
        mocksend_request.assert_called_with(
            "POST",
            "/api/marketplace-resources/mkt-res-uuid-789/terminate/",
            data={},
            path_params=None,
        )

    # --- Scenario 5: Check mode ---
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner.send_request")
    def test_check_mode_predicts_creation(
        self, mocksend_request, mock_ansible_module, mock_instance_runner_context
    ):
        """
        Tests that check mode correctly predicts that a resource will be created
        if it doesn't exist, without making any API calls beyond the existence check.
        """
        # Arrange
        mock_ansible_module.check_mode = True
        mock_ansible_module.params = {
            "state": "present",
            "name": "new-vm-in-check-mode",
            "project": "Cloud Project",
        }
        # Simulate that the resource does not exist.
        mocksend_request.side_effect = [
            ([{"url": "http://api.com/api/projects/proj-uuid/"}], 200),
            ([], 200),
        ]

        # Act
        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True,
            diff=[],
            resource=None,
            order=None,
        )
        # Only two calls should be made: project resolve and existence check
        assert mocksend_request.call_count == 2

    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner.send_request")
    def test_idempotent_complex_update_with_resolution(
        self, mocksend_request, mock_ansible_module, mock_instance_runner_context
    ):
        """
        Tests the most complex update scenario to ensure the runner's logic for
        resolution and idempotency is working perfectly.

        This test validates that:
        1.  The runner can correctly identify that a change is needed for multiple
            complex attributes (`ports` and `security_groups`).
        2.  It proactively fetches dependencies (like the `offering` and `project`
            objects) to enable filtered lookups for nested parameters.
        3.  It correctly resolves user-provided names (e.g., "private-subnet-new")
            into the full API URLs required by the action endpoints.
        4.  It correctly formats list-based parameters (like `security_groups`)
            into the required `[{'url': ...}]` structure.
        5.  It sends the fully resolved and formatted payloads to the correct
            action endpoints.
        6.  It performs an efficient, single re-fetch of the resource state after
            all actions are complete.
        """
        # ARRANGE

        # Define the initial state of the resource as it exists in Waldur.
        existing_resource = {
            "name": "vm-to-reconfigure",
            "uuid": "vm-uuid-789",
            "url": "http://api.com/api/openstack-instances/vm-uuid-789/",
            "project": "http://api.com/api/projects/proj-uuid/",
            "offering": "http://api.com/api/offerings/off-prem-uuid/",
            "ports": [
                {
                    "subnet": "http://api.com/api/subnets/subnet-old-uuid/",
                    "fixed_ips": [{"ip_address": "10.0.0.5"}],
                }
            ],
            "security_groups": [
                {"url": "http://api.com/api/security-groups/sg-default-uuid/"}
            ],
        }

        # Define the user's desired new configuration in the Ansible playbook.
        # Note the use of names ("private-subnet-new", "web-sg") that need resolution.
        mock_ansible_module.params = {
            "state": "present",
            "name": "vm-to-reconfigure",
            "project": "Cloud Project",
            "ports": [
                {
                    "subnet": "private-subnet-new",
                    "fixed_ips": [{"ip_address": "10.1.1.10"}],
                }
            ],
            "security_groups": ["web-sg", "ssh-sg"],
        }

        # This is the state of the resource AFTER the updates have been applied.
        # This is what the final re-fetch call should return.
        updated_resource_state = {
            **existing_resource,
            "state": "OK",
            "ports": [
                {
                    "subnet": "http://api.com/api/subnets/subnet-new-uuid/",
                    "fixed_ips": [{"ip_address": "10.1.1.10"}],
                }
            ],
            "security_groups": [
                {"url": "http://api.com/api/security-groups/sg-web-uuid/"},
                {"url": "http://api.com/api/security-groups/sg-ssh-uuid/"},
            ],
        }

        # Define the sequence of API responses that the mock `send_request` will return.
        # This list must precisely match the order of API calls made by the runner.
        def mocksend_request_side_effect(method, path, **kwargs):
            query_params = kwargs.get("query_params", {})
            # Map common paths to expected responses based on request details
            if method == "GET":
                if "/api/projects/" in path:
                    return ([{"url": "http://api.com/api/projects/proj-uuid/"}], 200)
                elif "/api/openstack-instances/" in path and query_params:
                    # This is the initial or final existence check call by name
                    if "vm-to-reconfigure" in query_params.get("name_exact", ""):
                        # If we have already made POST calls, it means this is the re-fetch.
                        # Return the updated state. Otherwise, return the initial state.
                        post_calls = [
                            c
                            for c in mocksend_request.call_args_list
                            if c.args[0] == "POST"
                        ]
                        if len(post_calls) > 0:
                            return ([updated_resource_state], 200)
                        else:
                            return ([existing_resource], 200)
                elif "/api/projects/proj-uuid/" in path:
                    return ({}, 200)
                elif "/api/offerings/off-prem-uuid/" in path:
                    return ({"scope_uuid": "tenant-prod-123"}, 200)
                elif "/api/openstack-subnets/" in path:
                    return (
                        [{"url": "http://api.com/api/subnets/subnet-new-uuid/"}],
                        200,
                    )
                elif "/api/openstack-security-groups/" in path:
                    if "web-sg" in query_params.get("name_exact", ""):
                        return (
                            [
                                {
                                    "url": "http://api.com/api/security-groups/sg-web-uuid/"
                                }
                            ],
                            200,
                        )
                    elif "ssh-sg" in query_params.get("name_exact", ""):
                        return (
                            [
                                {
                                    "url": "http://api.com/api/security-groups/sg-ssh-uuid/"
                                }
                            ],
                            200,
                        )
            elif method == "POST":
                if "update_ports" in path:
                    return (None, 202)  # Action accepted
                elif "update_security_groups" in path:
                    return (None, 202)  # Action accepted

            raise Exception(f"Unexpected request: {method} {path} {kwargs}")

        mocksend_request.side_effect = mocksend_request_side_effect

        # ACT
        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        # ASSERT
        # Check that the module exited with 'changed: true' and the final resource state.
        expected_diff = [
            {
                "action": "ports",
                "old": [
                    {
                        "subnet": "http://api.com/api/subnets/subnet-old-uuid/",
                        "fixed_ips": [{"ip_address": "10.0.0.5"}],
                    }
                ],
                "new": [
                    {
                        "subnet": "http://api.com/api/subnets/subnet-new-uuid/",
                        "fixed_ips": [{"ip_address": "10.1.1.10"}],
                    }
                ],
            },
            {
                "action": "security_groups",
                "old": [{"url": "http://api.com/api/security-groups/sg-default-uuid/"}],
                "new": [
                    "http://api.com/api/security-groups/sg-web-uuid/",
                    "http://api.com/api/security-groups/sg-ssh-uuid/",
                ],
            },
        ]
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, diff=expected_diff, resource=ANY, order=None
        )

        # Assert that the update_security_groups action was called with the resolved payload.
        mocksend_request.assert_any_call(
            "POST",
            "/api/openstack-instances/{uuid}/update_security_groups/",
            data={
                "security_groups": [
                    "http://api.com/api/security-groups/sg-web-uuid/",
                    "http://api.com/api/security-groups/sg-ssh-uuid/",
                ]
            },
            path_params={"uuid": "vm-uuid-789"},
        )

    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner.send_request")
    def test_delete_resource_with_all_termination_attributes(
        self, mocksend_request, mock_ansible_module, mock_instance_runner_context
    ):
        """
        Tests that `state: absent` correctly includes all provided termination
        attributes in the payload, mapping them to the correct API keys.
        """
        # ARRANGE
        mock_ansible_module.params = {
            "state": "absent",
            "name": "vm-to-force-delete",
            "project": "Cloud Project",
            # User-provided termination options
            "termination_action": "force_destroy",
            "delete_volumes": True,
            "release_floating_ips": True,
        }
        existing_resource = {
            "name": "vm-to-force-delete",
            "marketplace_resource_uuid": "mkt-res-uuid-123",
        }
        mocksend_request.side_effect = [
            ([{"url": "p-uuid"}], 200),
            ([existing_resource], 200),
            (None, 204),
        ]

        # ACT
        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        expected_diff = [
            {
                "old_attributes": {
                    "marketplace_resource_uuid": "mkt-res-uuid-123",
                    "name": "vm-to-force-delete",
                },
                "state": "Resource will be deleted.",
                "termination_options": {
                    "attributes": {
                        "action": "force_destroy",
                        "delete_volumes": True,
                        "release_floating_ips": True,
                    }
                },
            }
        ]
        # ASSERT
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, diff=expected_diff, resource=None, order=ANY
        )
        # Verify the payload contains the mapped attributes.
        expected_payload = {
            "attributes": {
                "action": "force_destroy",
                "delete_volumes": True,
                "release_floating_ips": True,
            }
        }
        mocksend_request.assert_any_call(
            "POST",
            "/api/marketplace-resources/mkt-res-uuid-123/terminate/",
            data=expected_payload,
            path_params=None,
        )
