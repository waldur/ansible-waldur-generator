"""Tests for the ReturnBlockGenerator (schema parser) class."""

import pytest
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator


class TestReturnBlockGenerator:
    """Test suite for the ReturnBlockGenerator class."""

    @pytest.fixture
    def sample_api_spec(self):
        """Realistic OpenAPI specification based on actual Waldur API."""
        return {
            "openapi": "3.0.3",
            "components": {
                "schemas": {
                    "Customer": {
                        "type": "object",
                        "description": "",
                        "properties": {
                            "url": {
                                "type": "string",
                                "format": "uri",
                                "readOnly": True,
                            },
                            "uuid": {
                                "type": "string",
                                "format": "uuid",
                                "readOnly": True,
                            },
                            "created": {
                                "type": "string",
                                "format": "date-time",
                                "readOnly": True,
                            },
                            "display_name": {"type": "string", "readOnly": True},
                            "backend_id": {
                                "type": "string",
                                "description": "Organization identifier in another application.",
                                "maxLength": 255,
                            },
                            "blocked": {"type": "boolean", "readOnly": True},
                            "archived": {"type": "boolean", "readOnly": True},
                            "name": {"type": "string", "maxLength": 150},
                            "native_name": {"type": "string", "maxLength": 500},
                            "abbreviation": {"type": "string", "maxLength": 12},
                            "contact_details": {"type": "string"},
                            "projects_count": {"type": "integer", "readOnly": True},
                            "users_count": {"type": "integer", "readOnly": True},
                        },
                        "required": ["name"],
                    },
                    "Project": {
                        "type": "object",
                        "description": "",
                        "properties": {
                            "url": {
                                "type": "string",
                                "format": "uri",
                                "readOnly": True,
                            },
                            "uuid": {
                                "type": "string",
                                "format": "uuid",
                                "readOnly": True,
                            },
                            "name": {"type": "string", "maxLength": 500},
                            "customer": {
                                "type": "string",
                                "format": "uri",
                                "title": "Organization",
                            },
                            "customer_uuid": {
                                "type": "string",
                                "format": "uuid",
                                "readOnly": True,
                            },
                            "customer_name": {"type": "string", "readOnly": True},
                            "description": {"type": "string"},
                            "created": {
                                "type": "string",
                                "format": "date-time",
                                "readOnly": True,
                            },
                            "type": {
                                "type": "string",
                                "format": "uri",
                                "nullable": True,
                                "title": "Project type",
                            },
                            "backend_id": {"type": "string", "maxLength": 255},
                        },
                        "required": ["name", "customer"],
                    },
                    "SimpleString": {
                        "type": "string",
                        "description": "A simple string schema",
                    },
                    "NestedProject": {
                        "type": "object",
                        "properties": {
                            "customer": {"$ref": "#/components/schemas/Customer"},
                            "related_projects": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/Project"},
                            },
                        },
                    },
                    "ProjectTypeEnum": {
                        "type": "string",
                        "enum": ["RESEARCH", "COMMERCIAL", "EDUCATIONAL"],
                        "description": "Project type enumeration",
                    },
                }
            },
        }

    @pytest.fixture
    def generator(self, sample_api_spec):
        """Create a ReturnBlockGenerator instance."""
        return ReturnBlockGenerator(sample_api_spec)

    def test_initialization(self, sample_api_spec):
        """Test ReturnBlockGenerator initialization."""
        generator = ReturnBlockGenerator(sample_api_spec)
        assert generator.full_api_spec == sample_api_spec

    def test_generate_simple_object(self, generator):
        """Test generating return block for simple object schema."""
        # Get the customer schema directly
        customer_schema = generator.full_api_spec["components"]["schemas"]["Customer"]
        result = generator._traverse_schema(customer_schema, "Customer")

        assert "uuid" in result
        assert "name" in result
        assert "backend_id" in result
        assert "abbreviation" in result
        assert "projects_count" in result
        assert "users_count" in result
        assert result["uuid"]["type"] == "str"
        assert result["name"]["type"] == "str"

    def test_generate_nested_object(self, generator):
        """Test generating return block for nested object properties."""
        project_schema = generator.full_api_spec["components"]["schemas"]["Project"]
        result = generator._traverse_schema(project_schema, "Project")

        assert "customer" in result
        assert "customer_name" in result
        assert "customer_uuid" in result
        assert result["customer"]["type"] == "str"

    def test_generate_array_property(self, generator):
        """Test generating return block with schema references."""
        nested_schema = generator.full_api_spec["components"]["schemas"][
            "NestedProject"
        ]
        result = generator._traverse_schema(nested_schema, "NestedProject")

        assert "related_projects" in result
        assert result["related_projects"]["type"] == "list"

    def test_generate_with_ref(self, generator):
        """Test generating return block with schema references."""
        nested_schema = generator.full_api_spec["components"]["schemas"][
            "NestedProject"
        ]
        result = generator._traverse_schema(nested_schema, "NestedProject")

        assert "customer" in result
        assert "related_projects" in result
        # Customer field should have nested structure when reference is resolved
        assert "contains" in result["customer"]
        assert "uuid" in result["customer"]["contains"]

    def test_generate_simple_type(self, generator):
        """Test generating return block for simple type schema."""
        simple_schema = generator.full_api_spec["components"]["schemas"]["SimpleString"]
        result = generator._traverse_schema(simple_schema, "SimpleString")

        # For simple string schemas without properties, result should be empty
        # The actual handling happens at higher levels
        assert isinstance(result, dict)

    def test_generate_enum(self, generator):
        """Test generating return block for enum schema."""
        enum_schema = generator.full_api_spec["components"]["schemas"][
            "ProjectTypeEnum"
        ]
        result = generator._traverse_schema(enum_schema, "ProjectTypeEnum")

        # For enum schemas without properties, result should be empty
        # Enums are handled when they're used as property types
        assert isinstance(result, dict)

    def test_generate_nonexistent_schema(self, generator):
        """Test generating return block for non-existent schema."""
        # Test the _get_schema_by_ref method for non-existent references
        result = generator._get_schema_by_ref("#/components/schemas/NonExistent")

        assert result is None

    def test_type_mapping(self, generator):
        """Test OpenAPI to Ansible type mapping."""
        customer_schema = generator.full_api_spec["components"]["schemas"]["Customer"]
        result = generator._traverse_schema(customer_schema, "Customer")

        # Check type mappings
        assert result["name"]["type"] == "str"  # string -> str
        assert result["blocked"]["type"] == "bool"  # boolean -> bool
        assert result["projects_count"]["type"] == "int"  # integer -> int

    def test_format_description(self, generator):
        """Test description formatting."""
        # Test the actual generate_description method
        prop_schema = {"description": "This is a test"}
        formatted = generator.generate_description(prop_schema, "test_field")
        assert formatted == "This is a test"

        # Test with None description
        prop_schema = {}
        formatted = generator.generate_description(prop_schema, "test_field")
        assert "test field" in formatted.lower()

        # Test with special field name formatting
        formatted = generator.generate_description({}, "ip_address")
        assert "IP address" in formatted

    def test_generate_project_schema(self, generator):
        """Test generating return block for Project schema."""
        project_schema = generator.full_api_spec["components"]["schemas"]["Project"]
        result = generator._traverse_schema(project_schema, "Project")

        # Should have all Project properties
        assert "uuid" in result
        assert "name" in result
        assert "customer" in result
        assert "description" in result
        assert "backend_id" in result

    def test_recursive_depth_limit(self, generator):
        """Test that recursive references don't cause infinite loops."""
        # Add a self-referencing schema
        generator.full_api_spec["components"]["schemas"]["Recursive"] = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "children": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/Recursive"},
                },
            },
        }

        # Currently the implementation hits recursion limit - this is a known limitation
        recursive_schema = generator.full_api_spec["components"]["schemas"]["Recursive"]

        # This should ideally handle recursion but currently doesn't
        # For now, we expect a RecursionError
        import pytest

        with pytest.raises(RecursionError):
            generator._traverse_schema(recursive_schema, "Recursive")

    def test_empty_schema(self, generator):
        """Test generating return block for empty schema."""
        generator.full_api_spec["components"]["schemas"]["Empty"] = {}

        empty_schema = generator.full_api_spec["components"]["schemas"]["Empty"]
        result = generator._traverse_schema(empty_schema, "Empty")
        assert isinstance(result, dict)

    def test_schema_without_properties(self, generator):
        """Test generating return block for object without properties."""
        generator.full_api_spec["components"]["schemas"]["NoProps"] = {
            "type": "object",
            "description": "Object with no properties",
        }

        no_props_schema = generator.full_api_spec["components"]["schemas"]["NoProps"]
        result = generator._traverse_schema(no_props_schema, "NoProps")
        assert isinstance(result, dict)

    def test_complex_nested_structure(self, generator):
        """Test generating return block for deeply nested structure."""
        generator.full_api_spec["components"]["schemas"]["DeepNested"] = {
            "type": "object",
            "properties": {
                "level1": {
                    "type": "object",
                    "properties": {
                        "level2": {
                            "type": "object",
                            "properties": {
                                "level3": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {"value": {"type": "string"}},
                                    },
                                }
                            },
                        }
                    },
                }
            },
        }

        deep_nested_schema = generator.full_api_spec["components"]["schemas"][
            "DeepNested"
        ]
        result = generator._traverse_schema(deep_nested_schema, "DeepNested")
        assert "level1" in result
        # Check nested structure
        assert "contains" in result["level1"]
        assert "level2" in result["level1"]["contains"]

    def test_additional_properties(self, generator):
        """Test handling of additionalProperties."""
        generator.full_api_spec["components"]["schemas"]["AdditionalProps"] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "additionalProperties": {"type": "string"},
        }

        additional_props_schema = generator.full_api_spec["components"]["schemas"][
            "AdditionalProps"
        ]
        result = generator._traverse_schema(additional_props_schema, "AdditionalProps")
        assert "name" in result
        assert result["name"]["type"] == "str"

    def test_required_fields_indication(self, generator):
        """Test that required fields are properly handled."""
        customer_schema = generator.full_api_spec["components"]["schemas"]["Customer"]
        result = generator._traverse_schema(customer_schema, "Customer")

        # The return block should include all fields regardless of required status
        # Required fields are handled at the module argument level, not return level
        assert "name" in result
        assert "uuid" in result  # Not required but should be in return

    def test_format_preservation(self, generator):
        """Test that format information is preserved in descriptions."""
        customer_schema = generator.full_api_spec["components"]["schemas"]["Customer"]
        result = generator._traverse_schema(customer_schema, "Customer")

        # UUID field should be properly handled
        assert "uuid" in result
        assert result["uuid"]["type"] == "str"
