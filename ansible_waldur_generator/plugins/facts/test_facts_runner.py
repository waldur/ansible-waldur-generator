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
            "project": "Cloud Project",  # This will be resolved
            "tenant": "Cloud Tenant",  # This will also be resolved
        }

        # --- MOCK THE RESOLVERS ---
        # Instead of mocking the internal _resolve_to_url method, we mock the
        # SDK functions that the runner is expected to call for resolution.

        # Simulate the 'project' resolver finding a project by name.
        project_resolver_mocks = mock_facts_runner_context["context_resolvers"][
            "project"
        ]
        project_resolver_mocks["list_func"].sync.return_value = [
            MagicMock(url="http://api.com/projects/proj-uuid/")
        ]

        # Simulate the 'tenant' resolver finding a tenant by name.
        tenant_resolver_mocks = mock_facts_runner_context["context_resolvers"]["tenant"]
        tenant_resolver_mocks["list_func"].sync.return_value = [
            MagicMock(url="http://api.com/tenants/tenant-uuid/")
        ]

        # Simulate the main `list_func` finding the final resource.
        found_resource = MagicMock()
        mock_facts_runner_context["list_func"].sync.return_value = [found_resource]

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        # 1. Verify that the resolver functions were called correctly.
        project_resolver_mocks["list_func"].sync.assert_called_once_with(
            client=runner.client, name_exact="Cloud Project"
        )
        tenant_resolver_mocks["list_func"].sync.assert_called_once_with(
            client=runner.client, name_exact="Cloud Tenant"
        )

        # 2. Verify `list_func` was called with all the resolved filters.
        mock_facts_runner_context["list_func"].sync.assert_called_once()
        call_args, call_kwargs = mock_facts_runner_context["list_func"].sync.call_args

        assert call_kwargs.get("name_exact") == "web-sg"
        assert call_kwargs.get("project_uuid") == "proj-uuid"
        assert call_kwargs.get("tenant_uuid") == "tenant-uuid"

        # 3. Check the final result.
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
