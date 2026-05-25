import pytest
from unittest.mock import patch
import uuid

from ansible_waldur_generator.helpers import AUTH_FIXTURE
from ansible_waldur_generator.plugins.facts.runner import FactsRunner


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


class TestFactsRunner:
    """
    Test suite for the FactsRunner logic.
    """

    # --- Scenario 1: Fetch a single resource by name successfully ---
    @patch("ansible_waldur_generator.plugins.facts.runner.FactsRunner.send_request")
    def test_fetch_resource_by_name(
        self, mocksend_request, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            **AUTH_FIXTURE,
            "name": "default-sg",
        }

        # Simulate the `send_request` finding exactly one resource.
        found_resource = {"name": "default-sg", "uuid": "sg-uuid"}
        mocksend_request.return_value = ([found_resource], 200)

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        mocksend_request.assert_called_once_with(
            "GET", "/api/security-groups/", query_params={"name_exact": "default-sg"}
        )
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=found_resource
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 2: Fetch a single resource by UUID successfully ---
    @patch("ansible_waldur_generator.plugins.facts.runner.FactsRunner.send_request")
    def test_fetch_resource_by_uuid(
        self, mocksend_request, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        test_uuid = str(uuid.uuid4())
        mock_ansible_module.params = {
            **AUTH_FIXTURE,
            "name": test_uuid,
        }

        # Simulate the `send_request` finding the resource.
        found_resource = {"name": "default-sg", "uuid": test_uuid}
        mocksend_request.return_value = (found_resource, 200)

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        mocksend_request.assert_called_once_with(
            "GET", "/api/security-groups/{uuid}/", path_params={"uuid": test_uuid}
        )
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=found_resource
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 3: Fetch a resource by name with context filters ---
    @patch("ansible_waldur_generator.plugins.facts.runner.FactsRunner.send_request")
    def test_fetch_resource_with_context_filters(
        self, mocksend_request, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            **AUTH_FIXTURE,
            "name": "web-sg",
            "project": "Cloud Project",
            "tenant": "Cloud Tenant",
        }

        # Simulate the resolver and the final resource fetch.
        found_resource = {"name": "web-sg", "uuid": "web-sg-uuid"}
        mocksend_request.side_effect = [
            (
                [{"url": "http://api.com/api/projects/proj-uuid/"}],
                200,
            ),  # project resolver
            (
                [{"url": "http://api.com/api/tenants/tenant-uuid/"}],
                200,
            ),  # tenant resolver
            ([found_resource], 200),  # final resource fetch
        ]

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        mocksend_request.assert_called_with(
            "GET",
            "/api/security-groups/",
            query_params={
                "name_exact": "web-sg",
                "project_uuid": "proj-uuid",
                "tenant_uuid": "tenant-uuid",
            },
        )
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=found_resource
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 4: Resource not found ---
    @patch("ansible_waldur_generator.plugins.facts.runner.FactsRunner.send_request")
    def test_resource_not_found_fails_when_many_is_false(
        self, mocksend_request, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            **AUTH_FIXTURE,
            "name": "non-existent-sg",
        }

        # Simulate `send_request` returning an empty list.
        mocksend_request.return_value = ([], 200)

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.fail_json.assert_called_once()
        call_args, call_kwargs = mock_ansible_module.fail_json.call_args
        assert "not found" in call_kwargs["msg"]
        mock_ansible_module.exit_json.assert_not_called()

    @patch("ansible_waldur_generator.plugins.facts.runner.FactsRunner.send_request")
    def test_resource_not_found_succeeds_when_many_is_true(
        self, mocksend_request, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        mock_facts_runner_context["many"] = True
        mock_ansible_module.params = {
            **AUTH_FIXTURE,
            "name": "non-existent-sg",
        }

        # Simulate `send_request` returning an empty list.
        mocksend_request.return_value = ([], 200)

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resources=[]
        )
        mock_ansible_module.fail_json.assert_not_called()

    # --- Scenario 5: Multiple resources found ---
    @patch("ansible_waldur_generator.plugins.facts.runner.FactsRunner.send_request")
    def test_multiple_resources_found_fails_when_many_is_false(
        self, mocksend_request, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        mock_ansible_module.params = {
            **AUTH_FIXTURE,
            "name": "ambiguous-name",
        }

        # Simulate `send_request` returning multiple resources.
        mocksend_request.return_value = (
            [
                {"name": "ambiguous-name", "uuid": "uuid1"},
                {"name": "ambiguous-name", "uuid": "uuid2"},
            ],
            200,
        )

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.fail_json.assert_called_once()
        call_args, call_kwargs = mock_ansible_module.fail_json.call_args
        assert "Multiple security_groups found" in call_kwargs["msg"]
        mock_ansible_module.warn.assert_not_called()
        mock_ansible_module.exit_json.assert_not_called()

    @patch("ansible_waldur_generator.plugins.facts.runner.FactsRunner.send_request")
    def test_multiple_resources_found_succeeds_when_many_is_true(
        self, mocksend_request, mock_ansible_module, mock_facts_runner_context
    ):
        # Arrange
        mock_facts_runner_context["many"] = True
        mock_ansible_module.params = {
            **AUTH_FIXTURE,
            "name": "ambiguous-name",
        }

        # Simulate `send_request` returning multiple resources.
        resource1 = {"name": "ambiguous-name", "uuid": "uuid1"}
        resource2 = {"name": "ambiguous-name", "uuid": "uuid2"}
        mocksend_request.return_value = ([resource1, resource2], 200)

        # Act
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)
        runner.run()

        # Assert
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resources=[resource1, resource2]
        )
        mock_ansible_module.fail_json.assert_not_called()
        mock_ansible_module.warn.assert_not_called()

    # --- Scenario 6: many=true follows pagination across all pages ---
    def test_many_follows_pagination_links(
        self, mock_ansible_module, mock_facts_runner_context
    ):
        """
        Regression test: with `many: true`, the runner must follow Waldur's
        'Link' pagination header and return resources from *every* page, not
        just the first page (default page size 10).
        """
        # Arrange
        mock_facts_runner_context["many"] = True
        mock_ansible_module.params = {**AUTH_FIXTURE}

        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)

        page1 = [{"uuid": f"sg-{i}"} for i in range(10)]
        page2 = [{"uuid": f"sg-{i}"} for i in range(10, 18)]
        responses = [
            (
                page1,
                '<https://api.example.com/api/security-groups/?page=2>; rel="next", '
                '<https://api.example.com/api/security-groups/?page=2>; rel="last"',
            ),
            (page2, ""),  # No 'next' link -> this is the last page.
        ]
        calls = []

        def fake_send_request(
            method, path, query_params=None, path_params=None, data=None
        ):
            calls.append((method, path, query_params))
            body, link = responses[len(calls) - 1]
            # Emulate the real send_request recording the response metadata.
            runner._last_response_info = {"status": 200, "link": link}
            return body, 200

        runner.send_request = fake_send_request

        # Act
        runner.run()

        # Assert: every resource across both pages is returned.
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resources=page1 + page2
        )
        mock_ansible_module.fail_json.assert_not_called()

        # Two requests were made: the first page (filters preserved verbatim,
        # no extra page-size hint) then the 'next' link followed verbatim.
        assert len(calls) == 2
        assert calls[0][1] == "/api/security-groups/"
        assert calls[1][1] == "https://api.example.com/api/security-groups/?page=2"

    def test_get_next_page_url_parsing(
        self, mock_ansible_module, mock_facts_runner_context
    ):
        """Unit test for the 'Link' header parser used to drive pagination."""
        runner = FactsRunner(mock_ansible_module, mock_facts_runner_context)

        # A full header exposes a 'next' link.
        runner._last_response_info = {
            "link": (
                '<https://api.example.com/api/x/?page=1>; rel="first", '
                '<https://api.example.com/api/x/?page=3>; rel="next", '
                '<https://api.example.com/api/x/?page=9>; rel="last"'
            )
        }
        assert runner._get_next_page_url() == "https://api.example.com/api/x/?page=3"

        # The last page has no 'next' relation.
        runner._last_response_info = {
            "link": (
                '<https://api.example.com/api/x/?page=1>; rel="first", '
                '<https://api.example.com/api/x/?page=8>; rel="prev"'
            )
        }
        assert runner._get_next_page_url() is None

        # A missing/empty header means there is no further page.
        runner._last_response_info = {}
        assert runner._get_next_page_url() is None
