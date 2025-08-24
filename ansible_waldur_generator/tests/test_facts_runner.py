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
        mock_module.check_mode = False

        # Mock the exit methods to prevent sys.exit and to capture their arguments.
        mock_module.exit_json = MagicMock()
        mock_module.fail_json = MagicMock()
        mock_module.warn = MagicMock()

        yield mock_module


@pytest.fixture
def mock_facts_runner_context():
    """A pytest fixture that provides a mocked context dictionary for the FactsRunner."""
    context = {
        "module_type": "facts",
        "resource_type": "security_group",
        "list_url": "/api/security-groups/",
        "retrieve_url": "/api/security-groups/{uuid}/",
        "identifier_param": "name",
        "resolvers": {
            "project": {
                "url": "/api/projects/",
                "error_message": "Project '{value}' not found.",
                "filter_key": "project_uuid",
            },
            "tenant": {
                "url": "/api/tenants/",
                "error_message": "Tenant '{value}' not found.",
                "filter_key": "tenant_uuid",
            },
        },
        "many": False,  # Explicitly set the default for clarity in tests
    }
    return context


# --- Test Class for FactsRunner ---


class TestFactsRunner:
    """
    Test suite for the FactsRunner logic.
    """

    # --- Scenario 1: Fetch a single resource by name successfully ---
    @patch("ansible_waldur_generator.plugins.facts.runner.FactsRunner._send_request")
    def test_fetch_resource_by_name(
        self, mock_send_request, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "name": "default-sg",
        }

        # Simulate the `_send_request` finding exactly one resource.
        found_resource = {"name": "default-sg", "uuid": "sg-uuid"}
        mock_send_request.return_value = [found_resource]

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        mock_send_request.assert_called_once_with(
            "GET", "/api/security-groups/", query_params={"name_exact": "default-sg"}
        )
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resources=[found_resource]
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 2: Fetch a single resource by UUID successfully ---
    @patch("ansible_waldur_generator.plugins.facts.runner.FactsRunner._send_request")
    def test_fetch_resource_by_uuid(
        self, mock_send_request, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        test_uuid = str(uuid.uuid4())
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "name": test_uuid,
        }

        # Simulate the `_send_request` finding the resource.
        found_resource = {"name": "default-sg", "uuid": test_uuid}
        mock_send_request.return_value = found_resource

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        mock_send_request.assert_called_once_with(
            "GET", "/api/security-groups/{uuid}/", path_params={"uuid": test_uuid}
        )
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resources=[found_resource]
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 3: Fetch a resource by name with context filters ---
    @patch("ansible_waldur_generator.plugins.facts.runner.FactsRunner._send_request")
    def test_fetch_resource_with_context_filters(
        self, mock_send_request, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com/",
            "access_token": "test-token",
            "name": "web-sg",
            "project": "Cloud Project",
            "tenant": "Cloud Tenant",
        }

        # Simulate the resolver and the final resource fetch.
        found_resource = {"name": "web-sg", "uuid": "web-sg-uuid"}
        mock_send_request.side_effect = [
            [{"url": "http://api.com/api/projects/proj-uuid/"}],  # project resolver
            [{"url": "http://api.com/api/tenants/tenant-uuid/"}],  # tenant resolver
            [found_resource],  # final resource fetch
        ]

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        mock_send_request.assert_called_with(
            "GET",
            "/api/security-groups/",
            query_params={
                "name_exact": "web-sg",
                "project_uuid": "proj-uuid",
                "tenant_uuid": "tenant-uuid",
            },
        )
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resources=[found_resource]
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 4: Resource not found ---
    @patch("ansible_waldur_generator.plugins.facts.runner.FactsRunner._send_request")
    def test_resource_not_found_fails_when_many_is_false(
        self, mock_send_request, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "name": "non-existent-sg",
        }

        # Simulate `_send_request` returning an empty list.
        mock_send_request.return_value = []

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.fail_json.assert_called_once()
        call_args, call_kwargs = mock_ansible_module.fail_json.call_args
        assert "not found" in call_kwargs["msg"]
        mock_ansible_module.exit_json.assert_not_called()

    @patch("ansible_waldur_generator.plugins.facts.runner.FactsRunner._send_request")
    def test_resource_not_found_succeeds_when_many_is_true(
        self, mock_send_request, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        mock_facts_runner_context["many"] = True
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "name": "non-existent-sg",
        }

        # Simulate `_send_request` returning an empty list.
        mock_send_request.return_value = []

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resources=[]
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 5: Multiple resources found ---
    @patch("ansible_waldur_generator.plugins.facts.runner.FactsRunner._send_request")
    def test_multiple_resources_found_fails_when_many_is_false(
        self, mock_send_request, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "name": "ambiguous-name",
        }

        # Simulate `_send_request` returning multiple resources.
        resource1 = {"name": "ambiguous-name", "uuid": "uuid1"}
        resource2 = {"name": "ambiguous-name", "uuid": "uuid2"}
        mock_send_request.return_value = [resource1, resource2]

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.fail_json.assert_called_once()
        call_args, call_kwargs = mock_ansible_module.fail_json.call_args
        assert "Multiple security_groups found" in call_kwargs["msg"]
        mock_ansible_module.warn.assert_not_called()
        mock_ansible_module.exit_json.assert_not_called()

    @patch("ansible_waldur_generator.plugins.facts.runner.FactsRunner._send_request")
    def test_multiple_resources_found_succeeds_when_many_is_true(
        self, mock_send_request, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        mock_facts_runner_context["many"] = True
        mock_ansible_module.params = {
            "api_url": "http://api.com",
            "access_token": "test-token",
            "name": "ambiguous-name",
        }

        # Simulate `_send_request` returning multiple resources.
        resource1 = {"name": "ambiguous-name", "uuid": "uuid1"}
        resource2 = {"name": "ambiguous-name", "uuid": "uuid2"}
        mock_send_request.return_value = [resource1, resource2]

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resources=[resource1, resource2]
        )
        mock_ansible_module.fail_json.assert_not_called()
        mock_ansible_module.warn.assert_not_called()
