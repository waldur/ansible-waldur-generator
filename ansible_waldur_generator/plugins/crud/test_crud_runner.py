import pytest
from unittest.mock import MagicMock, patch

# The class we are testing
from ansible_waldur_generator.plugins.crud.runner import CrudResourceRunner

# --- Mock Data Fixtures ---


@pytest.fixture
def mock_ansible_module():
    """A pytest fixture that provides a mocked AnsibleModule instance."""
    with patch(
        "ansible_waldur_generator.interfaces.runner.AnsibleModule"
    ) as mock_class:
        mock_module = mock_class.return_value
        mock_module.params = {}
        mock_module.check_mode = False
        mock_module.exit_json = MagicMock()
        mock_module.fail_json = MagicMock()
        yield mock_module


@pytest.fixture
def mock_crud_runner_context():
    """A pytest fixture that provides a mocked context dictionary for the CrudResourceRunner."""
    context = {
        "resource_type": "project",
        "existence_check_func": MagicMock(),
        "present_create_func": MagicMock(),
        "present_create_model_class": MagicMock(),
        "absent_destroy_func": MagicMock(),
        "absent_destroy_path_param": "uuid",
        "model_param_names": ["name", "description", "customer", "type"],
        "resolvers": {
            "customer": {
                "list_func": MagicMock(),
                "retrieve_func": MagicMock(),
                "error_message": "Customer '{value}' not found.",
            },
            "type": {
                "list_func": MagicMock(),
                "retrieve_func": MagicMock(),
                "error_message": "Project type '{value}' not found.",
            },
        },
    }
    return context


# --- Test Class for CrudResourceRunner ---


class TestCrudResourceRunner:
    """
    Test suite for the CrudResourceRunner logic.
    """

    # --- Scenario 1: Create a new resource successfully ---
    def test_create_new_resource(self, mock_ansible_module, mock_crud_runner_context):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "present",
            "name": "New Research Project",
            "description": "A cool project.",
            "customer": "Big Corp",  # This will be resolved
            "type": "Academic",  # This will also be resolved
        }

        # Simulate that the resource does NOT exist.
        mock_crud_runner_context["existence_check_func"].sync.return_value = []

        # Simulate the resolver functions returning objects with a 'url' attribute.
        mock_crud_runner_context["resolvers"]["customer"][
            "list_func"
        ].sync.return_value = [MagicMock(url="http://api.com/customers/cust-uuid/")]
        mock_crud_runner_context["resolvers"]["type"]["list_func"].sync.return_value = [
            MagicMock(url="http://api.com/project-types/type-uuid/")
        ]

        # Simulate the create call returning the new resource.
        new_resource = MagicMock()
        mock_crud_runner_context["present_create_func"].sync.return_value = new_resource

        # Act
        runner = CrudResourceRunner(mock_ansible_module, mock_crud_runner_context)
        runner.run()

        # Assert
        # Check that the create function was called.
        mock_crud_runner_context["present_create_func"].sync.assert_called_once()

        # Verify that the model class was instantiated with the correct, resolved data.
        mock_model = mock_crud_runner_context["present_create_model_class"]
        mock_model.assert_called_once_with(
            name="New Research Project",
            description="A cool project.",
            customer="http://api.com/customers/cust-uuid/",  # Resolved URL
            type="http://api.com/project-types/type-uuid/",  # Resolved URL
        )

        # Check that the final state is 'changed' and the new resource is returned.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=new_resource.to_dict.return_value
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 2: Resource already exists, no changes needed ---
    def test_resource_exists_no_change(
        self, mock_ansible_module, mock_crud_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "present",
            "name": "Existing Project",
        }

        # Simulate that the resource EXISTS.
        existing_resource = MagicMock()
        mock_crud_runner_context["existence_check_func"].sync.return_value = [
            existing_resource
        ]

        # Act
        runner = CrudResourceRunner(mock_ansible_module, mock_crud_runner_context)
        runner.run()

        # Assert
        # No state-changing functions should be called.
        mock_crud_runner_context["present_create_func"].sync.assert_not_called()
        mock_crud_runner_context["absent_destroy_func"].sync.assert_not_called()

        # Final state is not changed.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=existing_resource.to_dict.return_value
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 3: Delete an existing resource ---
    def test_delete_existing_resource(
        self, mock_ansible_module, mock_crud_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "absent",
            "name": "Project to Delete",
        }

        # Simulate the resource exists and has the required UUID for deletion.
        existing_resource = MagicMock(uuid="proj-to-delete-uuid")
        mock_crud_runner_context["existence_check_func"].sync.return_value = [
            existing_resource
        ]

        # Act
        runner = CrudResourceRunner(mock_ansible_module, mock_crud_runner_context)
        runner.run()

        # Assert
        # The destroy function must be called.
        destroy_func = mock_crud_runner_context["absent_destroy_func"]
        destroy_func.sync_detailed.assert_called_once()

        # Verify it was called with the correct UUID from the path parameter.
        call_args, call_kwargs = destroy_func.sync_detailed.call_args
        assert call_kwargs["uuid"] == "proj-to-delete-uuid"

        # The final state is changed, and the resource is now None.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=None
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 4: Delete a resource that is already absent ---
    def test_delete_non_existent_resource(
        self, mock_ansible_module, mock_crud_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "absent",
            "name": "Non-existent Project",
        }

        # Simulate the resource does not exist.
        mock_crud_runner_context["existence_check_func"].sync.return_value = []

        # Act
        runner = CrudResourceRunner(mock_ansible_module, mock_crud_runner_context)
        runner.run()

        # Assert
        # No state-changing functions should be called.
        mock_crud_runner_context["absent_destroy_func"].sync.assert_not_called()

        # The final state is not changed.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=None
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 5: Check mode ---
    def test_check_mode_predicts_creation(
        self, mock_ansible_module, mock_crud_runner_context
    ):
        # Arrange
        mock_ansible_module.check_mode = True  # Enable check mode
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "present",
            "name": "New Project",
        }

        # Simulate the resource does not exist.
        mock_crud_runner_context["existence_check_func"].sync.return_value = []

        # Act
        runner = CrudResourceRunner(mock_ansible_module, mock_crud_runner_context)
        runner.run()

        # Assert
        # No state-changing functions should be called in check mode.
        mock_crud_runner_context["present_create_func"].sync.assert_not_called()

        # Check mode should predict that a change would have occurred.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=None
        )
