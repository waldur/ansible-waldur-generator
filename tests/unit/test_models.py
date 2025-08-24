"""Tests for the models module."""

import pytest
from ansible_waldur_generator.models import ApiOperation, GenerationContext


class TestApiOperation:
    """Test suite for the ApiOperation dataclass."""

    def test_api_operation_creation(self):
        """Test creating an ApiOperation instance."""
        operation = ApiOperation(
            path="/api/test/",
            method="GET",
            operation_id="test_list"
        )
        
        assert operation.path == "/api/test/"
        assert operation.method == "GET"
        assert operation.operation_id == "test_list"
        assert operation.model_schema is None
        assert operation.raw_spec == {}

    def test_api_operation_with_schema(self):
        """Test creating an ApiOperation with schema and raw spec."""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        raw_spec = {"summary": "Test operation"}
        
        operation = ApiOperation(
            path="/api/test/",
            method="POST", 
            operation_id="test_create",
            model_schema=schema,
            raw_spec=raw_spec
        )
        
        assert operation.model_schema == schema
        assert operation.raw_spec == raw_spec

    def test_api_operation_immutability(self):
        """Test that ApiOperation is immutable (frozen dataclass)."""
        operation = ApiOperation(
            path="/api/test/",
            method="GET",
            operation_id="test_list"
        )
        
        with pytest.raises(Exception):  # FrozenInstanceError in Python 3.7+
            operation.path = "/api/modified/"


class TestGenerationContext:
    """Test suite for the GenerationContext dataclass."""

    def test_generation_context_creation(self):
        """Test creating a GenerationContext instance."""
        context = GenerationContext(
            argument_spec={"name": {"type": "str", "required": True}},
            module_filename="test_module.py",
            documentation={"module": "test_module"},
            examples=[{"name": "Test example"}],
            return_block={"resource": {"description": "The resource"}},
            runner_context={"api_url": "https://api.test.com"}
        )
        
        assert context.argument_spec == {"name": {"type": "str", "required": True}}
        assert context.module_filename == "test_module.py"
        assert context.documentation == {"module": "test_module"}
        assert context.examples == [{"name": "Test example"}]
        assert context.return_block == {"resource": {"description": "The resource"}}
        assert context.runner_context == {"api_url": "https://api.test.com"}

    def test_generation_context_mutability(self):
        """Test that GenerationContext is mutable (not frozen)."""
        context = GenerationContext(
            argument_spec={},
            module_filename="test.py",
            documentation={},
            examples=[],
            return_block={},
            runner_context={}
        )
        
        # Should be able to modify since it's not frozen
        context.module_filename = "modified.py"
        assert context.module_filename == "modified.py"

    def test_generation_context_with_complex_data(self):
        """Test GenerationContext with complex nested data structures."""
        complex_arg_spec = {
            "name": {
                "type": "str",
                "required": True,
                "description": "Resource name"
            },
            "metadata": {
                "type": "dict",
                "required": False,
                "options": {
                    "tags": {"type": "list", "elements": "str"},
                    "notes": {"type": "str"}
                }
            }
        }
        
        complex_examples = [
            {
                "name": "Create resource",
                "task": {
                    "name": "Create test resource",
                    "module": "test_module",
                    "args": {"name": "test", "state": "present"}
                }
            }
        ]
        
        context = GenerationContext(
            argument_spec=complex_arg_spec,
            module_filename="complex_module.py",
            documentation={"module": "complex_module", "version_added": "1.0.0"},
            examples=complex_examples,
            return_block={
                "resource": {
                    "description": "The created or found resource",
                    "type": "dict",
                    "returned": "always"
                }
            },
            runner_context={
                "operations": {
                    "list": "resources_list",
                    "create": "resources_create",
                    "update": "resources_partial_update",
                    "delete": "resources_destroy"
                }
            }
        )
        
        assert "metadata" in context.argument_spec
        assert context.argument_spec["metadata"]["options"]["tags"]["elements"] == "str"
        assert len(context.examples) == 1
        assert context.examples[0]["task"]["args"]["name"] == "test"
        assert "operations" in context.runner_context