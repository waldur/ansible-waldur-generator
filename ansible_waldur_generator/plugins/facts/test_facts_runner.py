import pytest
from unittest.mock import MagicMock, patch
import uuid

# The class we are testing
from ansible_waldur_generator.plugins.facts.runner import FactsRunner

# --- Mock Data Fixtures ---


@pytest.fixture
def mock_ansible_module():
    """A pytest fixture that provides a mocked AnsibleModule instance."""
    with patch(
        "ansible_waldur_generator.interfaces.runner.AnsibleModule"
    ) as mock_class:
        mock_module = mock_class.return_value
        mock_module.params = {}
        # `FactsRunner` does not use check_mode, but it's good practice to have it.
        mock_module.check_mode = False

        # Mock the exit methods to prevent sys.exit and to capture their arguments.
        mock_module.exit_json = MagicMock()
        mock_module.fail_json = MagicMock()
        mock_module.warn = MagicMock()

        yield mock_module


@pytest.fixture
def mock_facts_runner_context():
    """A pytest fixture that provides a mocked context dictionary for the FactsRunner."""
    # All function values are replaced with MagicMocks.
    context = {
        "module_type": "facts",
        "resource_type": "security_group",
        "list_func": MagicMock(),
        "retrieve_func": MagicMock(),
        "identifier_param": "name",
        "context_resolvers": {
            "project": {
                "list_func": MagicMock(),
                "retrieve_func": MagicMock(),
                "error_message": "Project '{value}' not found.",
                "filter_key": "project_uuid",
            },
            "tenant": {
                "list_func": MagicMock(),
                "retrieve_func": MagicMock(),
                "error_message": "Tenant '{value}' not found.",
                "filter_key": "tenant_uuid",
            },
        },
    }
    return context


# --- Test Class for FactsRunner ---


class TestFactsRunner:
    """
    Test suite for the FactsRunner logic.
    """

    # --- Scenario 1: Fetch a single resource by name successfully ---
    def test_fetch_resource_by_name(
        self, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "name": "default-sg",
        }

        # Simulate the `list_func` finding exactly one resource.
        found_resource = MagicMock()
        mock_facts_runner_context["list_func"].sync.return_value = [found_resource]

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        # Verify that `list_func` was called with the correct name filter.
        mock_facts_runner_context["list_func"].sync.assert_called_once()
        call_args, call_kwargs = mock_facts_runner_context["list_func"].sync.call_args
        assert call_kwargs["name_exact"] == "default-sg"

        # Verify that `retrieve_func` was NOT called.
        mock_facts_runner_context["retrieve_func"].sync.assert_not_called()

        # Check that the module exits with the found resource and `changed=False`.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=found_resource.to_dict.return_value
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 2: Fetch a single resource by UUID successfully ---
    def test_fetch_resource_by_uuid(
        self, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        test_uuid = str(uuid.uuid4())
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "name": test_uuid,
        }

        # Simulate the `retrieve_func` finding the resource.
        found_resource = MagicMock()
        mock_facts_runner_context["retrieve_func"].sync.return_value = found_resource

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        # Verify that `retrieve_func` was called with the correct UUID.
        mock_facts_runner_context["retrieve_func"].sync.assert_called_once()
        call_args, call_kwargs = mock_facts_runner_context[
            "retrieve_func"
        ].sync.call_args
        assert call_kwargs["uuid"] == test_uuid

        # Verify that `list_func` was NOT called.
        mock_facts_runner_context["list_func"].sync.assert_not_called()

        # Check that the module exits with the found resource.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=found_resource.to_dict.return_value
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 3: Fetch a resource by name with context filters ---
    def test_fetch_resource_with_context_filters(
        self, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "name": "web-sg",
            "project": "Cloud Project",
            "tenant": "Cloud Tenant",
        }

        # Simulate the resolver functions returning URLs for the context params.
        # We use side_effect to handle different calls to the same mocked `_resolve_to_url`.
        # This is a bit advanced, but shows how to handle it. A simpler way is to mock
        # the helper directly. Let's patch `_resolve_to_url` for simplicity here.

        def resolve_side_effect(*args, **kwargs):
            value = kwargs.get("value")
            if value == "Cloud Project":
                return "http://api.com/projects/proj-uuid/"
            if value == "Cloud Tenant":
                return "http://api.com/tenants/tenant-uuid/"
            return None

        # Simulate the `list_func` finding the resource.
        found_resource = MagicMock()
        mock_facts_runner_context["list_func"].sync.return_value = [found_resource]

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        # Patch the internal helper method for this specific test
        with patch.object(runner, "_resolve_to_url", side_effect=resolve_side_effect):
            runner.run()

        # Assert
        # Verify `list_func` was called with all filters.
        mock_facts_runner_context["list_func"].sync.assert_called_once()
        call_args, call_kwargs = mock_facts_runner_context["list_func"].sync.call_args
        assert call_kwargs["name_exact"] == "web-sg"
        assert call_kwargs["project_uuid"] == "proj-uuid"
        assert call_kwargs["tenant_uuid"] == "tenant-uuid"

        # Check the final result.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=found_resource.to_dict.return_value
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 4: Resource not found ---
    def test_resource_not_found(self, mock_ansible_module, mock_facts_runner_context):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "name": "non-existent-sg",
        }

        # Simulate `list_func` returning an empty list.
        mock_facts_runner_context["list_func"].sync.return_value = []

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        # The module should fail with a "not found" message.
        mock_ansible_module.fail_json.assert_called_once()
        call_args, call_kwargs = mock_ansible_module.fail_json.call_args
        assert "not found" in call_kwargs["msg"]

        mock_ansible_module.exit_json.assert_not_called()

    # --- Scenario 5: Multiple resources found, should warn and return the first ---
    def test_multiple_resources_found(
        self, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "name": "ambiguous-name",
        }

        # Simulate `list_func` returning multiple resources.
        resource1 = MagicMock()
        resource2 = MagicMock()
        mock_facts_runner_context["list_func"].sync.return_value = [
            resource1,
            resource2,
        ]

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        # A warning should be issued.
        mock_ansible_module.warn.assert_called_once()

        # The module should exit successfully with the *first* resource.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=resource1.to_dict.return_value
        )
        mock_ansible_module.fail_json.assert_not_called()
