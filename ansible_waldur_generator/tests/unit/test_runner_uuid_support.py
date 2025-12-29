import pytest
from unittest.mock import patch, MagicMock
from ansible_waldur_generator.interfaces.runner import BaseRunner
from ansible_waldur_generator.helpers import AUTH_FIXTURE


class TestBaseRunnerUuidSupport:
    @pytest.fixture
    def mock_runner_context(self):
        return {
            "resource_type": "test_resource",
            "check_url": "/api/test-resources/",
            "name_query_param": "name_exact",
            "check_filter_keys": {"tenant": "tenant_uuid"},
            "resolver_order": ["tenant"],
            "resolvers": {
                "tenant": {
                    "url": "/api/tenants/",
                    "error_message": "Tenant not found",
                }
            },
        }

    @pytest.fixture
    def mock_ansible_module(self):
        module = MagicMock()
        module.params = {**AUTH_FIXTURE}
        module.fail_json.side_effect = Exception("FailJsonCalled")
        return module

    @patch("ansible_waldur_generator.interfaces.runner.BaseRunner.send_request")
    def test_check_existence_by_explicit_uuid(
        self, mock_send_request, mock_ansible_module, mock_runner_context
    ):
        """Test that providing an explicit 'uuid' param triggers direct lookup."""
        mock_ansible_module.params["uuid"] = "explicit-uuid-123"
        mock_ansible_module.params["name"] = "ignored-name"
        mock_ansible_module.params["state"] = "present"

        mock_send_request.return_value = (
            {"uuid": "explicit-uuid-123", "name": "found"},
            200,
        )

        class ConcreteRunner(BaseRunner):
            def plan_creation(self):
                return []

            def plan_update(self):
                return []

            def plan_deletion(self):
                return []

        runner = ConcreteRunner(mock_ansible_module, mock_runner_context)
        runner.check_existence()

        mock_send_request.assert_called_once_with(
            "GET", "/api/test-resources/explicit-uuid-123/"
        )

    @patch("ansible_waldur_generator.interfaces.runner.BaseRunner.send_request")
    def test_check_existence_by_name_as_uuid(
        self, mock_send_request, mock_ansible_module, mock_runner_context
    ):
        """Test that providing a UUID in the 'name' field triggers a direct GET request."""
        mock_ansible_module.params["uuid"] = None
        mock_ansible_module.params["name"] = "d2258204-5178-4386-8968-07e1140974e4"
        mock_ansible_module.params["state"] = "present"

        mock_send_request.return_value = (
            {"uuid": "d2258204-5178-4386-8968-07e1140974e4", "name": "found"},
            200,
        )

        class ConcreteRunner(BaseRunner):
            def plan_creation(self):
                return []

            def plan_update(self):
                return []

            def plan_deletion(self):
                return []

        runner = ConcreteRunner(mock_ansible_module, mock_runner_context)
        runner.check_existence()

        mock_send_request.assert_called_once_with(
            "GET", "/api/test-resources/d2258204-5178-4386-8968-07e1140974e4/"
        )

    @patch("ansible_waldur_generator.interfaces.runner.BaseRunner.send_request")
    def test_check_existence_by_name_filter(
        self, mock_send_request, mock_ansible_module, mock_runner_context
    ):
        """Test that providing a name triggers a filtered list request."""
        mock_ansible_module.params["uuid"] = None
        mock_ansible_module.params["name"] = "resource-name"
        mock_ansible_module.params["state"] = "present"

        mock_send_request.return_value = (
            [{"uuid": "resource-uuid-123", "name": "resource-name"}],
            200,
        )

        class ConcreteRunner(BaseRunner):
            def plan_creation(self):
                return []

            def plan_update(self):
                return []

            def plan_deletion(self):
                return []

        runner = ConcreteRunner(mock_ansible_module, mock_runner_context)
        runner.resolver = MagicMock()

        runner.check_existence()

        mock_send_request.assert_called_once_with(
            "GET", "/api/test-resources/", query_params={"name_exact": "resource-name"}
        )

    @patch("ansible_waldur_generator.interfaces.runner.BaseRunner.send_request")
    def test_check_existence_no_name_with_filters(
        self, mock_send_request, mock_ansible_module, mock_runner_context
    ):
        """Test scanning without name but with required context filters."""
        mock_ansible_module.params["uuid"] = None
        mock_ansible_module.params["name"] = None
        mock_ansible_module.params["tenant"] = "tenant-uuid-123"
        mock_ansible_module.params["state"] = "present"

        # Mock resolver
        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = {
            "uuid": "tenant-uuid-resolved",
            "url": "url",
        }

        class ConcreteRunner(BaseRunner):
            def plan_creation(self):
                return []

            def plan_update(self):
                return []

            def plan_deletion(self):
                return []

        runner = ConcreteRunner(mock_ansible_module, mock_runner_context)
        runner.resolver = mock_resolver

        mock_send_request.return_value = ([], 200)

        runner.check_existence()

        mock_send_request.assert_called_once_with(
            "GET",
            "/api/test-resources/",
            query_params={"tenant_uuid": "tenant-uuid-resolved"},
        )
