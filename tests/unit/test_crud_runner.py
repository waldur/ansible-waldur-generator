import pytest
from unittest.mock import patch

from ansible_waldur_generator.plugins.crud.runner import CrudRunner


@pytest.fixture
def mock_crud_runner_context():
    context = {
        "resource_type": "project",
        "list_path": "/api/projects/",
        "create_path": "/api/projects/",
        "destroy_path": "/api/projects/{uuid}/",
        "update_path": "/api/projects/{uuid}/",
        "model_param_names": ["name", "description", "customer", "type"],
        "update_fields": ["description"],
        "update_actions": {},
        "path_param_maps": {},
        "resolvers": {
            "customer": {
                "url": "/api/customers/",
                "error_message": "Customer '{value}' not found.",
            },
            "type": {
                "url": "/api/project-types/",
                "error_message": "Project type '{value}' not found.",
            },
        },
    }
    return context


class TestCrudRunner:
    """
    Test suite for the CrudResourceRunner logic.
    """

    # --- Scenario 1: Create a new resource successfully ---
    @patch("ansible_waldur_generator.plugins.crud.runner.CrudRunner._send_request")
    def test_create_new_resource(
        self, mock_send_request, mock_ansible_module, mock_crud_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "present",
            "name": "New Research Project",
            "description": "A cool project.",
            "customer": "Big Corp",
            "type": "Academic",
        }

        # Simulate that the resource does NOT exist, and the create call returns the new resource.
        new_resource = {"name": "New Research Project", "uuid": "new-uuid"}
        mock_send_request.side_effect = [
            [],  # First call for existence check
            [{"url": "http://api.com/customers/cust-uuid/"}],  # Resolver for customer
            [{"url": "http://api.com/project-types/type-uuid/"}],  # Resolver for type
            new_resource,  # Create call
        ]

        # Act
        runner = CrudRunner(mock_ansible_module, mock_crud_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=new_resource
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 2: Resource already exists, no changes needed ---
    @patch("ansible_waldur_generator.plugins.crud.runner.CrudRunner._send_request")
    def test_resource_exists_no_change(
        self, mock_send_request, mock_ansible_module, mock_crud_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "present",
            "name": "Existing Project",
        }

        # Simulate that the resource EXISTS.
        existing_resource = {"name": "Existing Project", "uuid": "existing-uuid"}
        mock_send_request.return_value = [existing_resource]

        # Act
        runner = CrudRunner(mock_ansible_module, mock_crud_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=existing_resource
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 3: Delete an existing resource ---
    @patch("ansible_waldur_generator.plugins.crud.runner.CrudRunner._send_request")
    def test_delete_existing_resource(
        self, mock_send_request, mock_ansible_module, mock_crud_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "absent",
            "name": "Project to Delete",
        }

        # Simulate the resource exists and has the required UUID for deletion.
        existing_resource = {"name": "Project to Delete", "uuid": "proj-to-delete-uuid"}
        mock_send_request.side_effect = [
            [existing_resource],
            None,
        ]  # Existence check, then delete

        # Act
        runner = CrudRunner(mock_ansible_module, mock_crud_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=None
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 4: Delete a resource that is already absent ---
    @patch("ansible_waldur_generator.plugins.crud.runner.CrudRunner._send_request")
    def test_delete_non_existent_resource(
        self, mock_send_request, mock_ansible_module, mock_crud_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "absent",
            "name": "Non-existent Project",
        }

        # Simulate the resource does not exist.
        mock_send_request.return_value = []

        # Act
        runner = CrudRunner(mock_ansible_module, mock_crud_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=None
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 5: Check mode ---
    @patch("ansible_waldur_generator.plugins.crud.runner.CrudRunner._send_request")
    def test_check_mode_predicts_creation(
        self, mock_send_request, mock_ansible_module, mock_crud_runner_context
    ):
        # Arrange
        mock_ansible_module.check_mode = True
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "state": "present",
            "name": "New Project",
        }

        # Simulate the resource does not exist.
        mock_send_request.return_value = []

        # Act
        runner = CrudRunner(mock_ansible_module, mock_crud_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, resource=None
        )
