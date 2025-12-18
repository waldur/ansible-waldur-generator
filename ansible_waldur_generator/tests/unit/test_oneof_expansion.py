import pytest
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator
from ansible_waldur_generator.plugins.crud.plugin import CrudPlugin


class TestOneOfExpansion:
    @pytest.fixture
    def schema_parser(self):
        return ReturnBlockGenerator({})

    def test_top_level_oneof_expansion(self, schema_parser):
        """Test finding oneOf at root of schema."""
        schema = {
            "title": "TopLevel",
            "oneOf": [
                {
                    "title": "VariantA",
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                },
                {
                    "title": "VariantB",
                    "type": "object",
                    "properties": {"b": {"type": "integer"}},
                },
            ],
        }

        results = schema_parser.generate_expanded_samples(schema, "Resource")

        assert len(results) == 2
        assert results[0]["a"] == "string-value"
        assert results[0]["_variant_title"] == "VariantA"
        assert results[1]["b"] == 123
        assert results[1]["_variant_title"] == "VariantB"

    def test_nested_property_oneof_expansion(self, schema_parser):
        """Test finding oneOf nested in a property (like 'attributes')."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "attributes": {
                    "oneOf": [
                        {
                            "title": "TypeA",
                            "type": "object",
                            "properties": {"attr_a": {"type": "string"}},
                        },
                        {
                            "title": "TypeB",
                            "type": "object",
                            "properties": {"attr_b": {"type": "integer"}},
                        },
                    ]
                },
            },
        }

        results = schema_parser.generate_expanded_samples(schema, "Resource")

        assert len(results) == 2

        # Both should have the common base property
        # "name" heuristic returns f"My-Awesome-{resource_type}"
        assert results[0]["name"] == "My-Awesome-Resource"
        assert results[1]["name"] == "My-Awesome-Resource"

        # Check distinct attributes
        assert results[0]["attributes"]["attr_a"] == "string-value"
        assert results[0]["_variant_title"] == "TypeA"

        assert results[1]["attributes"]["attr_b"] == 123
        assert results[1]["_variant_title"] == "TypeB"

    def test_crud_plugin_oneof_type_inference(self):
        """Test that CrudPlugin infers type='dict' for properties with oneOf variants that are objects."""
        plugin = CrudPlugin()

        # Mock api_parser
        class MockApiParser:
            def get_operation(self, op_id):
                return None

            def get_query_parameters_for_operation(self, op_id):
                return []

            def get_schema_by_ref(self, ref):
                return {}

        # We need to mock how _build_parameters resolves schemas.
        # However, _build_parameters is complex.
        # Easier to check logic in isolation or mock the schema structure it expects.

        # Let's target the logic directly if possible or construct a minimal config.
        # The logic is in _build_parameters which iterates over 'create_operation.model_schema'.

        # Minimal mock of what's passed to _build_parameters logic
        from types import SimpleNamespace

        request_schema = {
            "type": "object",
            "properties": {
                "regular_str": {"type": "string"},
                "attributes": {
                    "oneOf": [
                        {"type": "object", "properties": {"foo": {"type": "string"}}},
                        {"type": "object", "properties": {"bar": {"type": "integer"}}},
                    ]
                    # Note: no explicit "type": "object" here, resembling the problematic schema
                },
            },
        }

        module_config = SimpleNamespace(
            create_operation=SimpleNamespace(model_schema=request_schema),
            parameters={},
            resolvers={},
            resource_type="MockResource",
            path_param_maps={},
            update_config=None,
        )

        api_parser = MockApiParser()

        # Run _build_parameters
        params = plugin._build_parameters(module_config, api_parser)

        assert "regular_str" in params
        assert params["regular_str"]["type"] == "str"

        assert "attributes" in params
        # This is the key assertion: it should be 'dict', not 'str'
        assert params["attributes"]["type"] == "dict"

    def test_allof_default_handling(self, schema_parser):
        """Test that default values in allOf structures are used for sample generation."""
        schema = {
            "type": "object",
            "properties": {
                "type": {
                    "allOf": [{"type": "string", "enum": ["A", "B"]}],
                    "default": "A",
                }
            },
        }

        result = schema_parser.generate_example_from_schema(schema, "Resource")

        assert "type" in result
        # This currently fails if 'default' is ignored and no 'example' or 'enum' (directly on prop) is found.
        # Although here 'enum' is in allOf, so it might resolve enum and pick first.
        # Let's verify strict default usage.
        assert result["type"] == "A"

        # Test case where default differs from first enum option (if feasible) or just a simple default
        schema_simple = {
            "type": "object",
            "properties": {
                "status": {"allOf": [{"type": "string"}], "default": "Active"}
            },
        }
        result_simple = schema_parser.generate_example_from_schema(
            schema_simple, "Resource"
        )
        assert result_simple["status"] == "Active"
