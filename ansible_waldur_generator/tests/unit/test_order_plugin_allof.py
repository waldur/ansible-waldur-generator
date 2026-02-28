"""
Tests for the OrderPlugin's handling of allOf schema constructs.

The OpenAPI spec uses `allOf` to compose schemas (e.g., wrapping a $ref with
additional properties like writeOnly or description). The order plugin must
resolve these correctly to determine parameter types and configure resolvers.

Specifically, this tests the fix for server_group-type fields where:
- The schema uses `allOf: [{$ref: '...'}]` instead of a direct `$ref`
- The referenced schema is `type: object` with a `url` property
- The parameter is resolved by the runner (user provides a string name)
- The resolver must wrap the URL in a dict (object_item_keys)
"""

import pytest

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.helpers import ValidationErrorCollector
from ansible_waldur_generator.models import ApiOperation, PluginModuleResolver
from ansible_waldur_generator.plugins.order.config import (
    OrderModuleConfig,
    ParameterConfig,
)
from ansible_waldur_generator.plugins.order.plugin import OrderPlugin


def _make_api_op(path="/api/test/", method="get"):
    return ApiOperation(path=path, method=method, operation_id="test_op")


def _make_resolver(path="/api/server-groups/"):
    return PluginModuleResolver(
        list_operation=_make_api_op(path=path, method="get"),
        retrieve_operation=_make_api_op(path=f"{path}{{uuid}}/", method="get"),
        error_message=None,
        filter_by=[],
    )


@pytest.fixture
def api_spec_with_allof():
    """An OpenAPI spec containing an allOf-wrapped object reference."""
    return {
        "paths": {},
        "components": {
            "schemas": {
                "ServerGroupHyperlinkRequest": {
                    "type": "object",
                    "properties": {"url": {"type": "string", "format": "uri"}},
                    "required": ["url"],
                },
            }
        },
    }


@pytest.fixture
def api_parser(api_spec_with_allof):
    collector = ValidationErrorCollector()
    return ApiSpecParser(api_spec_with_allof, collector)


@pytest.fixture
def order_plugin():
    return OrderPlugin()


@pytest.fixture
def module_config_with_server_group():
    """A minimal OrderModuleConfig that has server_group as a resolver."""
    return OrderModuleConfig(
        resource_type="Test Instance",
        existence_check_op=_make_api_op(),
        resolvers={
            "server_group": _make_resolver(),
        },
        attribute_params=[],
    )


class TestAllOfSchemaResolution:
    """Tests that allOf-wrapped $ref schemas are correctly resolved."""

    def test_allof_ref_resolved_to_object_type(
        self, order_plugin, api_parser, module_config_with_server_group
    ):
        """When a property uses allOf: [{$ref: ...}], the resolved type must be 'object'."""
        prop = {
            "allOf": [
                {"$ref": "#/components/schemas/ServerGroupHyperlinkRequest"}
            ],
            "writeOnly": True,
            "description": "Server group for scheduling policy",
        }

        result = order_plugin._create_param_config_from_schema(
            name="server_group",
            prop=prop,
            required_list=[],
            api_parser=api_parser,
            module_config=module_config_with_server_group,
        )

        assert result.type == "object", (
            f"Expected type 'object' for allOf-wrapped $ref, got '{result.type}'. "
            "The allOf construct must be resolved before determining the type."
        )
        assert len(result.properties) == 1
        assert result.properties[0].name == "url"

    def test_allof_ref_preserves_sibling_description(
        self, order_plugin, api_parser, module_config_with_server_group
    ):
        """Sibling properties (description, writeOnly) alongside allOf are preserved."""
        prop = {
            "allOf": [
                {"$ref": "#/components/schemas/ServerGroupHyperlinkRequest"}
            ],
            "writeOnly": True,
            "description": "Server group for scheduling policy",
        }

        result = order_plugin._create_param_config_from_schema(
            name="server_group",
            prop=prop,
            required_list=[],
            api_parser=api_parser,
            module_config=module_config_with_server_group,
        )

        assert result.description == "Server group for scheduling policy"


class TestResolvedObjectParamGeneratesObjectItemKeys:
    """Tests that resolved object-type params get object_item_keys in the resolver config."""

    def test_object_item_keys_set_for_resolved_object_param(self, order_plugin):
        """When a resolved param has type=object with properties, object_item_keys must be set."""
        module_config = OrderModuleConfig(
            resource_type="Test Instance",
            existence_check_op=_make_api_op(),
            resolvers={
                "server_group": _make_resolver(),
            },
            attribute_params=[
                ParameterConfig(
                    name="server_group",
                    type="object",
                    is_resolved=True,
                    properties=[ParameterConfig(name="url", type="string")],
                ),
            ],
        )

        resolvers = order_plugin._build_resolvers(module_config)

        assert "server_group" in resolvers
        assert resolvers["server_group"]["object_item_keys"] == {"create": "url"}, (
            "object_item_keys must map 'create' to 'url' for object-type resolved params. "
            'Without this, the resolver sends a plain URL string instead of {"url": "..."}.'
        )

    def test_object_item_keys_empty_for_string_param(self, order_plugin):
        """When a resolved param has type=string, object_item_keys must be empty."""
        module_config = OrderModuleConfig(
            resource_type="Test Instance",
            existence_check_op=_make_api_op(),
            resolvers={
                "ssh_public_key": _make_resolver(path="/api/keys/"),
            },
            attribute_params=[
                ParameterConfig(
                    name="ssh_public_key",
                    type="string",
                    is_resolved=True,
                ),
            ],
        )

        resolvers = order_plugin._build_resolvers(module_config)

        assert resolvers["ssh_public_key"]["object_item_keys"] == {}


class TestResolvedObjectParamAnsibleSpec:
    """Tests that resolved object-type params generate 'str' Ansible input type."""

    def test_resolved_object_param_generates_str_ansible_type(
        self, order_plugin, api_parser, module_config_with_server_group
    ):
        """A resolved object-type param must be 'str' in Ansible spec (user provides a name)."""
        param = ParameterConfig(
            name="server_group",
            type="object",
            is_resolved=True,
            description="Server group for scheduling policy",
            properties=[ParameterConfig(name="url", type="string")],
        )

        spec = order_plugin._build_spec_for_param(
            param, api_parser, module_config_with_server_group
        )

        assert spec["type"] == "str", (
            f"Expected Ansible type 'str' for resolved object param, got '{spec['type']}'. "
            "Resolved params accept a string name from the user; the resolver handles conversion."
        )

    def test_non_resolved_object_param_generates_dict_ansible_type(
        self, order_plugin, api_parser, module_config_with_server_group
    ):
        """A non-resolved object-type param must be 'dict' in Ansible spec."""
        param = ParameterConfig(
            name="some_config",
            type="object",
            is_resolved=False,
            description="Some config object",
            properties=[ParameterConfig(name="key", type="string")],
        )

        spec = order_plugin._build_spec_for_param(
            param, api_parser, module_config_with_server_group
        )

        assert spec["type"] == "dict"
