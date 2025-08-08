import pytest
from unittest.mock import MagicMock, patch

# The class we are testing
from ansible_waldur_generator.plugins.order.runner import OrderRunner
from waldur_api_client.models import OrderState

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
    # All function and class values are replaced with MagicMocks.
    # This allows us to track calls and define return values for each test.
    context = {
        "resource_type": "OpenStack volume",
        "existence_check_func": MagicMock(),
        "existence_check_filter_keys": {"project": "project_uuid"},
        "update_func": MagicMock(),
        "update_model_class": MagicMock(),
        "update_check_fields": ["description"],
        "order_create_func": MagicMock(),
        "order_poll_func": MagicMock(),
        "terminate_func": MagicMock(),
        "order_model_class": MagicMock(),
        "terminate_model_class": MagicMock(),
        "attribute_param_names": ["size", "type", "description"],
        "resolvers": {
            "project": {  # Add project resolver for existence check
                "list_func": MagicMock(),
                "retrieve_func": MagicMock(),
                "error_message": "Project '{value}' not found.",
            },
            "offering": {
                "list_func": MagicMock(),
                "retrieve_func": MagicMock(),
                "error_message": "Offering '{value}' not found.",
            },
            "type": {
                "list_func": MagicMock(),
                "retrieve_func": MagicMock(),
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
    def test_create_new_resource_successfully(
        self, mock_ansible_module, mock_runner_context
    ):
        # Arrange
        # User wants to create a resource that does not exist yet.
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "present",
            "name": "new-volume",
            "project": "Cloud Project",
            "offering": "Standard Volume",
            "size": 10,
            "wait": True,  # Test the waiting logic
        }

        # Simulate that the resource does NOT exist.
        mock_runner_context["existence_check_func"].sync.return_value = []

        # Simulate resolver calls returning URLs
        mock_runner_context["resolvers"]["project"]["list_func"].sync.return_value = [
            MagicMock(url="http://api.com/projects/proj-uuid/")
        ]
        mock_runner_context["resolvers"]["offering"]["list_func"].sync.return_value = [
            MagicMock(url="http://api.com/offerings/off-uuid/")
        ]

        # Simulate the order creation process
        mock_order = MagicMock(uuid="order-uuid")
        mock_runner_context["order_create_func"].sync.return_value = mock_order

        # Simulate the polling process: first 'executing', then 'done'.
        poll_call_1 = MagicMock(state=OrderState.EXECUTING)
        poll_call_2 = MagicMock(state=OrderState.DONE)
        mock_runner_context["order_poll_func"].sync.side_effect = [
            poll_call_1,
            poll_call_2,
        ]

        # Act
        runner = OrderRunner(mock_ansible_module, mock_runner_context)
        runner.run()

        # Assert
        # Check that the create function was called
        mock_runner_context["order_create_func"].sync.assert_called_once()

        # Check that polling happened twice
        assert mock_runner_context["order_poll_func"].sync.call_count == 2

        # Check that the final state is 'changed'
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True,
            resource=None,  # Resource is None as creation doesn't return it directly
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 2: Resource already exists, no changes needed ---
    def test_resource_exists_no_change(self, mock_ansible_module, mock_runner_context):
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
        existing_resource = MagicMock(description="current description")
        mock_runner_context["existence_check_func"].sync.return_value = [
            existing_resource
        ]

        # Act
        runner = OrderRunner(mock_ansible_module, mock_runner_context)
        runner.run()

        # Assert
        # Neither create, update, nor delete should be called.
        mock_runner_context["order_create_func"].sync.assert_not_called()
        mock_runner_context["update_func"].sync.assert_not_called()
        mock_runner_context["terminate_func"].sync.assert_not_called()

        # Final state is not changed.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=existing_resource.to_dict.return_value
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 3: Update an existing resource ---
    def test_update_existing_resource(self, mock_ansible_module, mock_runner_context):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "present",
            "name": "existing-volume",
            "project": "Cloud Project",
            "description": "a new description",  # The new value
        }

        # Simulate that the resource exists with an old description.
        existing_resource = MagicMock(description="old description", uuid="res-uuid")
        mock_runner_context["existence_check_func"].sync.return_value = [
            existing_resource
        ]

        # Simulate the update call returning the updated resource.
        updated_resource = MagicMock(description="a new description")
        mock_runner_context["update_func"].sync.return_value = updated_resource

        # Act
        runner = OrderRunner(mock_ansible_module, mock_runner_context)
        runner.run()

        # Assert
        # The update function must be called.
        mock_runner_context["update_func"].sync.assert_called_once()

        # Verify the payload sent to the update function
        # The update model class should be instantiated with the new description.
        mock_runner_context["update_model_class"].assert_called_with(
            description="a new description"
        )

        # The final state is changed, and the updated resource is returned.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=updated_resource.to_dict.return_value
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 4: Delete an existing resource ---
    def test_delete_existing_resource(self, mock_ansible_module, mock_runner_context):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "absent",
            "name": "volume-to-delete",
            "project": "Cloud Project",
        }

        # Simulate the resource exists and has the required UUID for termination.
        existing_resource = MagicMock(marketplace_resource_uuid="mkt-uuid")
        mock_runner_context["existence_check_func"].sync.return_value = [
            existing_resource
        ]

        # Act
        runner = OrderRunner(mock_ansible_module, mock_runner_context)
        runner.run()

        # Assert
        # The terminate function must be called.
        mock_runner_context["terminate_func"].sync.assert_called_once()

        # Verify it was called with the correct UUID.
        call_args, call_kwargs = mock_runner_context["terminate_func"].sync.call_args
        assert call_kwargs["uuid"] == "mkt-uuid"

        # The final state is changed, and the resource is now None.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=None
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 5: Delete a resource that is already absent ---
    def test_delete_non_existent_resource(
        self, mock_ansible_module, mock_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "absent",
            "name": "non-existent",
        }

        # Simulate the resource does not exist.
        mock_runner_context["existence_check_func"].sync.return_value = []

        # Act
        runner = OrderRunner(mock_ansible_module, mock_runner_context)
        runner.run()

        # Assert
        # No API calls to change state should be made.
        mock_runner_context["terminate_func"].sync.assert_not_called()

        # The final state is not changed.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=None
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 6: Check mode ---
    def test_check_mode_predicts_creation(
        self, mock_ansible_module, mock_runner_context
    ):
        # Arrange
        mock_ansible_module.check_mode = True  # Enable check mode
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "present",
            "name": "new-volume",
        }

        # Simulate the resource does not exist.
        mock_runner_context["existence_check_func"].sync.return_value = []

        # Act
        runner = OrderRunner(mock_ansible_module, mock_runner_context)
        runner.run()

        # Assert
        # No state-changing functions should be called.
        mock_runner_context["order_create_func"].sync.assert_not_called()

        # Check mode should predict that a change would have occurred.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=None
        )
