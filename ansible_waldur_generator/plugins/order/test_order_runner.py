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

    # --- Scenario 1: Create a new comprehensive resource ---
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner._send_request")
    def test_create_instance_with_full_payload(
        self, mock_send_request, mock_ansible_module, mock_instance_runner_context
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

        # Arrange: Mock the sequence of all required API calls.
        mock_send_request.side_effect = [
            # 1. Existence Check Phase
            [{"url": "http://api.com/api/projects/proj-prod-uuid/"}],
            [],  # Instance does not exist
            # 2. Create Phase: Parameter Resolution
            [{"url": "http://api.com/api/projects/proj-prod-uuid/"}],  # project
            [
                {
                    "url": "http://api.com/api/offerings/off-prem-uuid/",
                    "scope_uuid": "tenant-prod-123",
                }
            ],  # offering
            [{"url": "http://api.com/api/flavors/flavor-large-uuid/"}],  # flavor
            [{"url": "http://api.com/api/images/img-ubuntu-uuid/"}],  # image
            [
                {"url": "http://api.com/api/security-groups/sg-web-uuid/"}
            ],  # security_groups[0]
            [
                {"url": "http://api.com/api/security-groups/sg-ssh-uuid/"}
            ],  # security_groups[1]
            [
                {"url": "http://api.com/api/subnets/subnet-private-uuid/"}
            ],  # ports[0].subnet
            [
                {"url": "http://api.com/api/subnets/subnet-public-uuid/"}
            ],  # floating_ips[0].subnet
            [{"url": "http://api.com/api/ssh-keys/key-admin-uuid/"}],  # ssh_public_key
            # 3. Create Phase: Order Submission
            {"uuid": "order-xyz-789"},
            # 4. Wait Phase
            {"state": "done"},
            [
                {"url": "http://api.com/api/projects/proj-prod-uuid/"}
            ],  # Final project resolve
            [{"name": "prod-web-vm-01", "state": "OK"}],  # Final existence check
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

        # Assert: Final state is correct
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource={"name": "prod-web-vm-01", "state": "OK"}
        )

        # Assert: The order creation call was made with the exact expected payload
        order_creation_call = mock_send_request.call_args_list[11]
        assert order_creation_call.args == ("POST", "/api/marketplace-orders/")
        assert order_creation_call.kwargs["data"] == expected_payload

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
