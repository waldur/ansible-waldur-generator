import pytest
from unittest.mock import MagicMock
from ansible_waldur_generator.interfaces.resolver import ParameterResolver


class TestParameterResolverValidation:
    @pytest.fixture
    def mock_runner(self):
        runner = MagicMock()
        runner.module = MagicMock()
        runner.module.params = {}
        runner.context = {
            "resolvers": {
                "project": {
                    "url": "/api/projects/",
                    "name_query_param": "name_exact",
                    "filter_by": [
                        {
                            "source_param": "customer",
                            "target_key": "customer",  # The API filter param, AND we assume the field name on the object
                            "source_key": "uuid",
                        }
                    ],
                },
                "customer": {
                    "url": "/api/customers/",
                },
            }
        }
        # Helper to simulate _is_uuid
        runner._is_uuid = lambda x: len(x) == 36 and "-" in x
        return runner

    def test_validation_success_matching_uuid(self, mock_runner):
        """Test validation passes when project's customer matches provided customer."""
        resolver = ParameterResolver(mock_runner)

        # Setup: User provides customer UUID and project Name
        customer_uuid = "1b6045bb-b302-4235-857c-674313f83737"
        project_name = "MyProject"

        mock_runner.module.params = {"customer": customer_uuid, "project": project_name}

        # Mock API response using side_effect to handle both list and detail lookups
        def side_effect(method, url, query_params=None):
            if "MyProject" in str(query_params) or "proj-uuid" in url:
                # Project found
                return (
                    [
                        {
                            "uuid": "proj-uuid",
                            "name": "MyProject",
                            "url": "http://api/projects/proj-uuid/",
                            "customer": f"http://api/customers/{customer_uuid}/",
                        }
                    ],
                    200,
                )
            if customer_uuid in url:
                # Customer lookup by UUID (detail view) returns dict
                return (
                    {
                        "uuid": customer_uuid,
                        "name": "MyCustomer",
                        "url": f"http://api/customers/{customer_uuid}/",
                    },
                    200,
                )
            return ([], 404)

        mock_runner.send_request.side_effect = side_effect

        # Execute
        resolved_url = resolver.resolve("project", project_name)

        # Verify
        assert resolved_url == "http://api/projects/proj-uuid/"
        # Should not fail

    def test_validation_failure_mismatch(self, mock_runner):
        """Test validation fails when project's customer does NOT match provided customer."""
        resolver = ParameterResolver(mock_runner)

        # Setup: User provides Customer A, but Project belongs to Customer B
        customer_a_uuid = "1b6045bb-b302-4235-857c-aaaaaaaaaaaa"
        customer_b_uuid = "1b6045bb-b302-4235-857c-bbbbbbbbbbbb"
        project_name = "MyProject"

        mock_runner.module.params = {
            "customer": customer_a_uuid,
            "project": project_name,
        }

        # Mock API response
        def side_effect(method, url, query_params=None):
            if "MyProject" in str(query_params) or "proj-uuid" in url:
                return (
                    [
                        {
                            "uuid": "proj-uuid",
                            "name": "MyProject",
                            "url": "http://api/projects/proj-uuid/",
                            "customer": f"http://api/customers/{customer_b_uuid}/",
                        }
                    ],
                    200,
                )
            if customer_a_uuid in url:
                return (
                    {
                        "uuid": customer_a_uuid,
                        "name": "Customer A",
                        "url": f"http://api/customers/{customer_a_uuid}/",
                    },
                    200,
                )
            return ([], 404)

        mock_runner.send_request.side_effect = side_effect

        # Setup fail_json to raise exception so we can catch it
        mock_runner.module.fail_json.side_effect = RuntimeError("Validation Failed")

        # Execute
        with pytest.raises(RuntimeError, match="Validation Failed"):
            resolver.resolve("project", project_name)

        # Verify call args
        args, _ = mock_runner.module.fail_json.call_args
        assert "Consistency error" in str(args) or "Consistency error" in str(
            mock_runner.module.fail_json.call_args
        )

    def test_validation_skipped_if_customer_not_provided(self, mock_runner):
        """Test validation is skipped if dependency parameter is not provided."""
        resolver = ParameterResolver(mock_runner)

        # Setup: User only provides Project, no Customer
        project_name = "MyProject"

        mock_runner.module.params = {
            # "customer" is missing
            "project": project_name
        }

        # Mock API response
        def side_effect(method, url, query_params=None):
            if "MyProject" in str(query_params) or "proj-uuid" in url:
                return (
                    [
                        {
                            "uuid": "proj-uuid",
                            "name": "MyProject",
                            "url": "http://api/projects/proj-uuid/",
                            "customer": "http://api/customers/some-uuid/",
                        }
                    ],
                    200,
                )
            return ([], 404)

        mock_runner.send_request.side_effect = side_effect

        # Execute
        resolved_url = resolver.resolve("project", project_name)

        # Verify
        assert resolved_url == "http://api/projects/proj-uuid/"
        # Should not call fail_json
