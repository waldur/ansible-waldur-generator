"""
Tests for 'facts' modules built on a non-GET retrieve operation that returns a
secret (e.g. revealing an API key with POST .../reveal/), and for list
operations that cannot look an object up by name.
"""

import uuid
from unittest.mock import patch

import pytest

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.helpers import AUTH_FIXTURE, ValidationErrorCollector
from ansible_waldur_generator.plugins.facts.plugin import FactsPlugin
from ansible_waldur_generator.plugins.facts.runner import FactsRunner
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator

KEY_PROPERTIES = {
    "uuid": {"type": "string", "format": "uuid"},
    "client_id": {"type": "string"},
    "state": {"type": "string"},
}

API_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {
        "/api/keys/": {
            "get": {
                "operationId": "keys_list",
                "parameters": [
                    {"name": "state", "in": "query", "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/Key"},
                                }
                            }
                        }
                    }
                },
            }
        },
        "/api/keys/{uuid}/": {
            "get": {
                "operationId": "keys_retrieve",
                "parameters": [{"name": "uuid", "in": "path", "required": True}],
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Key"}
                            }
                        }
                    }
                },
            }
        },
        "/api/keys/{uuid}/reveal/": {
            "post": {
                "operationId": "keys_reveal",
                "parameters": [{"name": "uuid", "in": "path", "required": True}],
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/RevealedKey"}
                            }
                        }
                    }
                },
            }
        },
    },
    "components": {
        "schemas": {
            "Key": {"type": "object", "properties": KEY_PROPERTIES},
            "RevealedKey": {
                "type": "object",
                "properties": {
                    **KEY_PROPERTIES,
                    "api_key": {"type": "string", "description": "Api key"},
                },
            },
        }
    },
}


def _generate(raw_config):
    return FactsPlugin().generate(
        "key_reveal",
        raw_config,
        ApiSpecParser(API_SPEC, ValidationErrorCollector()),
        "test",
        "keys",
        ReturnBlockGenerator(API_SPEC),
    )


REVEAL_CONFIG = {
    "plugin": "facts",
    "resource_type": "key",
    "identifier_param": "uuid",
    "operations": {"retrieve": "keys_reveal"},
    "sensitive_fields": ["api_key"],
}


class TestRevealPlugin:
    def test_runner_context_uses_retrieve_method(self):
        context = _generate(dict(REVEAL_CONFIG))
        assert context.runner_context["retrieve_method"] == "POST"
        assert context.runner_context["retrieve_url"] == "/api/keys/{uuid}/reveal/"
        assert context.runner_context["name_lookup"] is False

    def test_identifier_is_uuid_only(self):
        context = _generate(dict(REVEAL_CONFIG))
        description = context.argument_spec["uuid"]
        assert description["required"] is True
        assert "The UUID of the key." in context.documentation["options"]["uuid"][
            "description"
        ]

    def test_sensitive_field_is_flagged_in_return_docs(self):
        context = _generate(dict(REVEAL_CONFIG))
        api_key_doc = context.return_block["resource"]["contains"]["api_key"]
        assert "no_log: true" in api_key_doc["description"]
        assert "sample" not in api_key_doc
        client_id_doc = context.return_block["resource"]["contains"]["client_id"]
        assert "no_log" not in client_id_doc["description"]

    def test_example_task_uses_no_log(self):
        context = _generate(dict(REVEAL_CONFIG))
        lookup_task = context.examples[0]["tasks"][0]
        assert lookup_task["no_log"] is True
        assert "var" not in context.examples[0]["tasks"][1]["ansible.builtin.debug"]

    def test_unknown_sensitive_field_is_rejected(self):
        with pytest.raises(ValueError, match="not_there"):
            _generate({**REVEAL_CONFIG, "sensitive_fields": ["not_there"]})

    def test_missing_explicit_operation_is_rejected(self):
        with pytest.raises(ValueError, match="keys_missing"):
            _generate({**REVEAL_CONFIG, "operations": {"retrieve": "keys_missing"}})

    def test_list_without_name_filter_has_no_name_lookup(self):
        context = _generate(
            {
                "plugin": "facts",
                "resource_type": "key",
                "many": True,
                "identifier_param": "uuid",
                "base_operation_id": "keys",
            }
        )
        assert context.runner_context["retrieve_method"] == "GET"
        assert context.runner_context["name_lookup"] is False
        assert context.examples[0]["tasks"][1]["ansible.builtin.debug"] == {
            "var": "resource_info.resources"
        }


@pytest.fixture
def reveal_context():
    return {
        "resource_type": "key",
        "list_url": "",
        "retrieve_url": "/api/keys/{uuid}/reveal/",
        "retrieve_method": "POST",
        "identifier_param": "uuid",
        "name_lookup": False,
        "resolvers": {},
        "many": False,
        "inferred_filter_params": [],
    }


class TestRevealRunner:
    @patch("ansible_waldur_generator.plugins.facts.runner.FactsRunner.send_request")
    def test_reveal_posts_and_reports_no_change(
        self, mock_send_request, mock_ansible_module, reveal_context
    ):
        key_uuid = uuid.uuid4().hex
        mock_ansible_module.params = {**AUTH_FIXTURE, "uuid": key_uuid}
        revealed = {"uuid": key_uuid, "client_id": "AKID", "api_key": "secret"}
        mock_send_request.return_value = (revealed, 200)

        FactsRunner(mock_ansible_module, reveal_context).run()

        mock_send_request.assert_called_once_with(
            "POST", "/api/keys/{uuid}/reveal/", path_params={"uuid": key_uuid}
        )
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resource=revealed
        )

    @patch("ansible_waldur_generator.plugins.facts.runner.FactsRunner.send_request")
    def test_name_is_rejected_without_name_lookup(
        self, mock_send_request, mock_ansible_module, reveal_context
    ):
        mock_ansible_module.params = {**AUTH_FIXTURE, "uuid": "my-key"}
        mock_ansible_module.fail_json.side_effect = Exception("FailJsonCalled")

        with pytest.raises(Exception, match="FailJsonCalled"):
            FactsRunner(mock_ansible_module, reveal_context).run()

        assert "must be the UUID" in mock_ansible_module.fail_json.call_args.kwargs[
            "msg"
        ]
        mock_send_request.assert_not_called()

    @patch("ansible_waldur_generator.plugins.facts.runner.FactsRunner.send_request")
    def test_list_without_identifier_still_lists(
        self, mock_send_request, mock_ansible_module, reveal_context
    ):
        context = {
            **reveal_context,
            "list_url": "/api/keys/",
            "retrieve_url": "/api/keys/{uuid}/",
            "retrieve_method": "GET",
            "many": True,
            "inferred_filter_params": ["state"],
        }
        mock_ansible_module.params = {**AUTH_FIXTURE, "uuid": None, "state": "OK"}

        with patch.object(
            FactsRunner, "_fetch_all_pages", return_value=[{"uuid": "k1"}]
        ) as mock_fetch:
            FactsRunner(mock_ansible_module, context).run()

        mock_fetch.assert_called_once_with("/api/keys/", query_params={"state": "OK"})
        mock_send_request.assert_not_called()
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, resources=[{"uuid": "k1"}]
        )
