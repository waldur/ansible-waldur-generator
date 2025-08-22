import pytest
from unittest.mock import MagicMock, patch

# The class we are testing
from ansible_waldur_generator.plugins.order.runner import OrderRunner


# --- Pytest Fixtures for Mocks ---


@pytest.fixture
def mock_ansible_module():
    """
    A pytest fixture that provides a mocked AnsibleModule instance for each test.
    This prevents tests from interfering with each other and from exiting the test runner.
    """
    # We patch 'AnsibleModule' in the runner's namespace to avoid import issues.
    with patch(
        "ansible_waldur_generator.interfaces.runner.AnsibleModule"
    ) as mock_class:
        mock_module = mock_class.return_value
        mock_module.params = {}  # Start with empty params for each test
        mock_module.check_mode = False

        # Mock the exit methods to prevent sys.exit and to capture their arguments
        mock_module.exit_json = MagicMock()
        mock_module.fail_json = MagicMock()
        mock_module.warn = MagicMock()

        yield mock_module


@pytest.fixture
def mock_instance_runner_context():
    """
    A pytest fixture providing a realistic, mocked context dictionary for a full-featured
    OpenStack instance module, including nested resolvers.
    """
    context = {
        "resource_type": "OpenStack instance",
        "existence_check_url": "/api/openstack-instances/",
        "existence_check_filter_keys": {"project": "project_uuid"},
        "update_url": "/api/openstack-instances/{uuid}/",
        "update_check_fields": ["description", "name"],
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
                "list_item_key": "url",
                "filter_by": [
                    {
                        "source_param": "offering",
                        "source_key": "scope_uuid",
                        "target_key": "tenant_uuid",
                    }
                ],
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
    }
    return context


# --- Test Class for OrderRunner ---


class TestOrderRunner:
    """
    A comprehensive test suite for the OrderRunner logic, covering creation,
    updates, deletion, and advanced resolver scenarios.
    """

    # --- Scenario 1: Create a new resource with list and dependent resolvers ---
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner._send_request")
    def test_create_instance_with_all_resolver_types(
        self, mock_send_request, mock_ansible_module, mock_instance_runner_context
    ):
        """
        Tests the primary success path: creating a new instance. This test validates:
        1. Correct dependency resolution (flavor and image depend on offering).
        2. Correct list resolution for security groups.
        3. The final order payload is constructed correctly.
        4. The runner waits for the order to complete.
        """
        # Arrange: Set up the user-provided parameters in the Ansible module.
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "token",
            "state": "present",
            "wait": True,
            "name": "new-vm-01",
            "project": "Cloud Project",
            "offering": "OpenStack Instance",
            "flavor": "g-standard-2",
            "image": "Ubuntu 22.04",
            "security_groups": ["web-sg", "ssh-sg"],
            "system_volume_size": 20,
        }

        # Arrange: Mock the sequence of API calls the runner is expected to make.
        # This sequence is critical to understanding the runner's internal logic flow.
        mock_send_request.side_effect = [
            # --- Existence Check Phase ---
            [{"url": "http://api.com/api/projects/proj-uuid/"}],  # 1. Resolve project
            [],  # 2. Check existence (returns empty, so we proceed to create)
            # --- Parameter Resolution Phase (in _resolve_all_parameters) ---
            # Pass 1: Resolving parameters with no dependencies
            [
                {"url": "http://api.com/api/projects/proj-uuid/"}
            ],  # 3. Resolve project again
            [
                {
                    "url": "http://api.com/api/offerings/off-uuid/",
                    "scope_uuid": "tenant-uuid-from-offering",
                }
            ],  # 4. Resolve offering
            # Pass 2: Resolving parameters with dependencies
            [
                {"url": "http://api.com/api/flavors/flavor-uuid/"}
            ],  # 5. Resolve flavor (filtered by tenant_uuid)
            [
                {"url": "http://api.com/api/images/image-uuid/"}
            ],  # 6. Resolve image (filtered by tenant_uuid)
            [
                {"url": "http://api.com/api/security-groups/sg1-uuid/"}
            ],  # 7. Resolve first security group
            [
                {"url": "http://api.com/api/security-groups/sg2-uuid/"}
            ],  # 8. Resolve second security group
            # --- Order Creation Phase ---
            {"uuid": "order-uuid-123"},  # 9. Create marketplace order
            # --- Wait for Order Phase ---
            {"state": "executing"},  # 10. First poll
            {"state": "done"},  # 11. Second poll shows completion
            # --- Final State Fetch Phase (after order is 'done') ---
            [
                {"url": "http://api.com/api/projects/proj-uuid/"}
            ],  # 12. Resolve project for final check_existence
            [
                {"name": "new-vm-01", "state": "OK"}
            ],  # 13. Re-check existence to get final resource state
        ]

        # Act: Run the runner's main method.
        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        # Assert: Verify the final outcome.
        # The module should exit successfully, indicating a change was made.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource={"name": "new-vm-01", "state": "OK"}
        )
        mock_ansible_module.fail_json.assert_not_called()

        # Assert: Verify the API calls were made as expected.
        # Check that the dependent resolvers passed the correct filter.
        mock_send_request.assert_any_call(
            "GET",
            "/api/openstack-flavors/",
            query_params={
                "name": "g-standard-2",
                "tenant_uuid": "tenant-uuid-from-offering",
            },
        )
        mock_send_request.assert_any_call(
            "GET",
            "/api/openstack-security-groups/",
            query_params={"name": "web-sg", "tenant_uuid": "tenant-uuid-from-offering"},
        )

        # Assert: Verify the order payload was constructed correctly.
        create_order_call = mock_send_request.call_args_list[8]
        order_payload = create_order_call.kwargs["data"]
        assert order_payload["project"] == "http://api.com/api/projects/proj-uuid/"
        assert order_payload["offering"] == "http://api.com/api/offerings/off-uuid/"
        attributes = order_payload["attributes"]
        assert attributes["flavor"] == "http://api.com/api/flavors/flavor-uuid/"
        assert attributes["security_groups"] == [
            {"url": "http://api.com/api/security-groups/sg1-uuid/"},
            {"url": "http://api.com/api/security-groups/sg2-uuid/"},
        ]

    # --- Scenario 2: Resource already exists, no changes needed ---
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner._send_request")
    def test_resource_exists_no_change(
        self, mock_send_request, mock_ansible_module, mock_instance_runner_context
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
        mock_send_request.side_effect = [
            [{"url": "http://api.com/api/projects/proj-uuid/"}],
            [existing_resource],
        ]

        # Act
        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=existing_resource
        )

    # --- Scenario 3: Update an existing resource ---
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner._send_request")
    def test_update_existing_resource(
        self, mock_send_request, mock_ansible_module, mock_instance_runner_context
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
        mock_send_request.side_effect = [
            [{"url": "http://api.com/api/projects/proj-uuid/"}],  # Resolve project
            [existing_resource],  # Existence check finds the resource
            updated_resource,  # The PATCH call returns the updated resource
        ]

        # Act
        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=updated_resource
        )
        # Verify the PATCH call was made correctly.
        mock_send_request.assert_called_with(
            "PATCH",
            "/api/openstack-instances/{uuid}/",
            data={"description": "a new description"},
            path_params={"uuid": "vm-uuid-456"},
        )

    # --- Scenario 4: Delete an existing resource ---
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner._send_request")
    def test_delete_existing_resource(
        self, mock_send_request, mock_ansible_module, mock_instance_runner_context
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
        mock_send_request.side_effect = [
            [{"url": "http://api.com/api/projects/proj-uuid/"}],  # Resolve project
            [existing_resource],  # Existence check finds it
            None,  # The terminate call returns 204 No Content
        ]

        # Act
        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=None
        )
        # Verify the termination call was made to the correct endpoint.
        mock_send_request.assert_called_with(
            "POST",
            "/api/marketplace-resources/mkt-res-uuid-789/terminate/",
            data={},
        )

    # --- Scenario 5: Check mode ---
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner._send_request")
    def test_check_mode_predicts_creation(
        self, mock_send_request, mock_ansible_module, mock_instance_runner_context
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
        mock_send_request.side_effect = [
            [{"url": "http://api.com/api/projects/proj-uuid/"}],
            [],
        ]

        # Act
        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=None
        )
        # Only two calls should be made: project resolve and existence check
        assert mock_send_request.call_count == 2

    # Scenario 6. Create instance with nested port/subnet resolution
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner._send_request")
    def test_create_instance_with_nested_subnet_resolution(
        self, mock_send_request, mock_ansible_module, mock_instance_runner_context
    ):
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "token",
            "state": "present",
            "wait": True,
            "name": "vm-with-ports",
            "project": "Cloud Project",
            "offering": "OpenStack Instance",
            "ports": [
                {
                    "subnet": "private-net-subnet",
                    "fixed_ips": [{"ip_address": "192.168.1.100"}],
                }
            ],
            "floating_ips": [{"subnet": "public-fip-subnet"}],
        }
        mock_send_request.side_effect = [
            [{"url": "http://api.com/api/projects/proj-uuid/"}],
            [],
            [{"url": "http://api.com/api/projects/proj-uuid/"}],
            [
                {
                    "url": "http://api.com/api/offerings/off-uuid/",
                    "scope_uuid": "tenant-123",
                }
            ],
            [{"url": "http://api.com/api/subnets/private-subnet-uuid/"}],
            [{"url": "http://api.com/api/subnets/public-subnet-uuid/"}],
            {"uuid": "order-abc"},
            {"state": "done"},
            [{"url": "http://api.com/api/projects/proj-uuid/"}],
            [{"name": "vm-with-ports", "state": "OK"}],
        ]

        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource={"name": "vm-with-ports", "state": "OK"}
        )
        mock_send_request.assert_any_call(
            "GET",
            "/api/openstack-subnets/",
            query_params={"name": "private-net-subnet", "tenant_uuid": "tenant-123"},
        )
        mock_send_request.assert_any_call(
            "GET",
            "/api/openstack-subnets/",
            query_params={"name": "public-fip-subnet", "tenant_uuid": "tenant-123"},
        )

        create_order_call = mock_send_request.call_args_list[6]
        order_payload = create_order_call.kwargs["data"]
        attributes = order_payload["attributes"]

        assert attributes["ports"] == [
            {
                "subnet": "http://api.com/api/subnets/private-subnet-uuid/",
                "fixed_ips": [{"ip_address": "192.168.1.100"}],
            }
        ]
        assert attributes["floating_ips"] == [
            {"subnet": "http://api.com/api/subnets/public-subnet-uuid/"}
        ]
