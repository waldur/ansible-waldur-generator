import pytest
from unittest.mock import MagicMock, patch

# The class we are testing
from ansible_waldur_generator.plugins.order.runner import OrderRunner

# --- Mock Data Fixtures ---


@pytest.fixture
def mock_ansible_module():
    """A pytest fixture that provides a mocked AnsibleModule instance."""
    # We patch 'AnsibleModule' in the runner's namespace to avoid import issues.
    with patch(
        "ansible_waldur_generator.interfaces.runner.AnsibleModule"
    ) as mock_class:
        mock_module = mock_class.return_value
        mock_module.params = {}  # Start with empty params
        mock_module.check_mode = False

        # Mock the exit methods to prevent sys.exit and to capture their arguments
        mock_module.exit_json = MagicMock()
        mock_module.fail_json = MagicMock()

        yield mock_module


@pytest.fixture
def mock_runner_context():
    """A pytest fixture that provides a mocked context dictionary for the runner."""
    context = {
        "resource_type": "OpenStack volume",
        "existence_check_url": "/api/resources/",
        "existence_check_filter_keys": {"project": "project_uuid"},
        "update_url": "/api/resources/",
        "update_check_fields": ["description"],
        "attribute_param_names": ["size", "type", "description"],
        "resolvers": {
            "project": {
                "url": "/api/projects/",
                "error_message": "Project '{value}' not found.",
            },
            "offering": {
                "url": "/api/offerings/",
                "error_message": "Offering '{value}' not found.",
            },
            "type": {
                "url": "/api/volume-types/",
                "error_message": "Volume type '{value}' not found.",
            },
        },
    }
    return context


# --- Test Class for OrderRunner ---


class TestOrderRunner:
    """
    Test suite for the OrderRunner logic.
    """

    # --- Scenario 1: Create a new resource ---
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner._send_request")
    def test_create_new_resource_successfully(
        self, mock_send_request, mock_ansible_module, mock_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "present",
            "name": "new-volume",
            "project": "Cloud Project",
            "offering": "Standard Volume",
            "size": 10,
            "wait": True,
        }

        # Simulate the sequence of API calls
        # The sequence is:
        # 1. Project resolver in check_existence: GET /api/projects/?name=Cloud Project
        # 2. Existence check: GET /api/resources/?name_exact=new-volume&project_uuid=proj-uuid
        # 3. Project resolver in create: GET /api/projects/?name=Cloud Project (cached or called again)
        # 4. Offering resolver in create: GET /api/offerings/?name=Standard Volume
        # 5. Order creation: POST /api/marketplace-orders/
        # 6. Order polling: GET /api/marketplace-orders/order-uuid (first poll)
        # 7. Order polling: GET /api/marketplace-orders/order-uuid (second poll - done)

        mock_send_request.side_effect = [
            [
                {"url": "http://api.com/projects/proj-uuid/"}
            ],  # project resolver for check_existence
            [],  # existence check returns empty (resource doesn't exist)
            [
                {"url": "http://api.com/projects/proj-uuid/"}
            ],  # project resolver for create
            [{"url": "http://api.com/offerings/off-uuid/"}],  # offering resolver
            {"uuid": "order-uuid"},  # order creation
            {"state": "executing"},  # first poll
            {"state": "done"},  # second poll
        ]

        # Act
        runner = OrderRunner(mock_ansible_module, mock_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=None
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 2: Resource already exists, no changes needed ---
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner._send_request")
    def test_resource_exists_no_change(
        self, mock_send_request, mock_ansible_module, mock_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "present",
            "name": "existing-volume",
            "project": "Cloud Project",
            "description": "current description",
        }

        # Simulate that the resource EXISTS.
        existing_resource = {
            "name": "existing-volume",
            "description": "current description",
        }
        mock_send_request.side_effect = [
            [{"url": "http://api.com/projects/proj-uuid/"}],  # project resolver
            [existing_resource],  # existence check returns the resource
        ]

        # Act
        runner = OrderRunner(mock_ansible_module, mock_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=existing_resource
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 3: Update an existing resource ---
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner._send_request")
    def test_update_existing_resource(
        self, mock_send_request, mock_ansible_module, mock_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "present",
            "name": "existing-volume",
            "project": "Cloud Project",
            "description": "a new description",
        }

        # Simulate the resource exists and the update call.
        existing_resource = {
            "name": "existing-volume",
            "description": "old description",
            "uuid": "res-uuid",
        }
        updated_resource = {
            "name": "existing-volume",
            "description": "a new description",
            "uuid": "res-uuid",
        }
        mock_send_request.side_effect = [
            [{"url": "http://api.com/projects/proj-uuid/"}],  # project resolver
            [existing_resource],  # existence check
            updated_resource,  # update call
        ]

        # Act
        runner = OrderRunner(mock_ansible_module, mock_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=updated_resource
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 4: Delete an existing resource ---
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner._send_request")
    def test_delete_existing_resource(
        self, mock_send_request, mock_ansible_module, mock_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "absent",
            "name": "volume-to-delete",
            "project": "Cloud Project",
        }

        # Simulate the resource exists.
        existing_resource = {
            "name": "volume-to-delete",
            "marketplace_resource_uuid": "mkt-uuid",
        }
        mock_send_request.side_effect = [
            [{"url": "http://api.com/projects/proj-uuid/"}],  # project resolver
            [existing_resource],  # existence check
            None,  # terminate call
        ]

        # Act
        runner = OrderRunner(mock_ansible_module, mock_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=None
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 5: Delete a resource that is already absent ---
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner._send_request")
    def test_delete_non_existent_resource(
        self, mock_send_request, mock_ansible_module, mock_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "absent",
            "name": "non-existent",
        }

        # Simulate the resource does not exist.
        mock_send_request.return_value = []

        # Act
        runner = OrderRunner(mock_ansible_module, mock_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=None
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 6: Check mode ---
    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner._send_request")
    def test_check_mode_predicts_creation(
        self, mock_send_request, mock_ansible_module, mock_runner_context
    ):
        # Arrange
        mock_ansible_module.check_mode = True
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "present",
            "name": "new-volume",
        }

        # Simulate the resource does not exist.
        mock_send_request.return_value = []

        # Act
        runner = OrderRunner(mock_ansible_module, mock_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=None
        )
