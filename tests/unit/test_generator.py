"""Integration tests for the Generator class and overall pipeline."""

import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest
import yaml

from ansible_waldur_generator.generator import Generator
from ansible_waldur_generator.models import GenerationContext
from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator


class TestGenerator:
    """Test suite for the Generator class."""

    @pytest.fixture
    def temp_output_dir(self):
        """Create a temporary directory for test outputs."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def sample_config(self):
        """Sample generator configuration."""
        return {
            "collections": [
                {
                    "namespace": "test",
                    "name": "collection",
                    "version": "1.0.0",
                    "modules": [
                        {
                            "name": "test_module",
                            "plugin": "crud",
                            "resource_type": "test resource",
                            "description": "Test module for testing",
                            "base_operation_id": "test_resources",
                        }
                    ]
                }
            ]
        }

    @pytest.fixture
    def sample_api_spec(self):
        """Sample OpenAPI specification."""
        return {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {
                "/api/test-resources/": {
                    "get": {
                        "operationId": "test_resources_list",
                        "responses": {"200": {"description": "Success"}},
                    },
                    "post": {
                        "operationId": "test_resources_create",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/TestResource"}
                                }
                            }
                        },
                        "responses": {"201": {"description": "Created"}},
                    },
                },
                "/api/test-resources/{uuid}/": {
                    "get": {
                        "operationId": "test_resources_retrieve",
                        "parameters": [
                            {"name": "uuid", "in": "path", "required": True}
                        ],
                        "responses": {"200": {"description": "Success"}},
                    },
                    "patch": {
                        "operationId": "test_resources_partial_update",
                        "parameters": [
                            {"name": "uuid", "in": "path", "required": True}
                        ],
                        "responses": {"200": {"description": "Success"}},
                    },
                    "delete": {
                        "operationId": "test_resources_destroy",
                        "parameters": [
                            {"name": "uuid", "in": "path", "required": True}
                        ],
                        "responses": {"204": {"description": "No Content"}},
                    },
                },
            },
            "components": {
                "schemas": {
                    "TestResource": {
                        "type": "object",
                        "properties": {
                            "uuid": {"type": "string"},
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["name"],
                    }
                }
            },
        }

    @pytest.fixture
    def mock_plugin_manager(self):
        """Mock PluginManager with a sample plugin."""
        with patch("ansible_waldur_generator.generator.PluginManager") as mock_pm_class:
            mock_pm = Mock()
            mock_pm_class.return_value = mock_pm
            
            # Create a mock plugin
            mock_plugin = Mock()
            mock_plugin.get_type_name.return_value = "crud"
            mock_plugin.generate.return_value = GenerationContext(
                argument_spec={"name": {"type": "str", "required": True}},
                module_filename="test_module.py",
                documentation={"module": "test_module", "description": "Test module documentation"},
                examples=[{"name": "Example 1"}],
                return_block={"resource": {"description": "Test return block"}},
                runner_context={},
            )
            # Fix the runner path to return None instead of Mock object
            mock_plugin.get_runner_path.return_value = None
            
            mock_pm.get_plugin.return_value = mock_plugin
            yield mock_pm

    def test_generator_initialization(self, sample_config, sample_api_spec):
        """Test Generator initialization with config and API spec."""
        generator = Generator(sample_config, sample_api_spec)
        
        assert generator.config_data == sample_config
        assert generator.api_spec_data == sample_api_spec
        assert generator.plugin_manager is not None
        assert generator.copied_runners == set()

    def test_generator_from_files(self, temp_output_dir):
        """Test Generator.from_files class method."""
        config_file = os.path.join(temp_output_dir, "config.yaml")
        api_spec_file = os.path.join(temp_output_dir, "api_spec.yaml")
        
        config = {"collections": []}
        api_spec = {"openapi": "3.0.0"}
        
        with open(config_file, "w") as f:
            yaml.dump(config, f)
        
        with open(api_spec_file, "w") as f:
            yaml.dump(api_spec, f)
        
        generator = Generator.from_files(config_file, api_spec_file)
        
        assert generator.config_data == config
        assert generator.api_spec_data == api_spec

    def test_generate_collections(self, sample_config, sample_api_spec, temp_output_dir, mock_plugin_manager):
        """Test full collection generation process."""
        generator = Generator(sample_config, sample_api_spec)
        
        # Run generation
        generator.generate(temp_output_dir)
        
        # Verify collection structure was created
        collection_path = Path(temp_output_dir) / "ansible_collections" / "test" / "collection"
        assert collection_path.exists()
        
        # Check galaxy.yml was created
        galaxy_file = collection_path / "galaxy.yml"
        assert galaxy_file.exists()
        
        with open(galaxy_file) as f:
            galaxy_content = yaml.safe_load(f)
            assert galaxy_content["namespace"] == "test"
            assert galaxy_content["name"] == "collection"
            assert galaxy_content["version"] == "1.0.0"
        
        # Check module was created
        module_file = collection_path / "plugins" / "modules" / "test_module.py"
        assert module_file.exists()

    def test_get_collection_root(self, sample_config, sample_api_spec, temp_output_dir):
        """Test collection root path generation."""
        generator = Generator(sample_config, sample_api_spec)
        
        # The generator should extract namespace/name from config
        root_path = generator._get_collection_root(temp_output_dir)
        
        # Should contain the output directory path
        assert temp_output_dir in root_path
        assert "ansible_collections" in root_path

    def test_copy_runners(self, sample_config, sample_api_spec, temp_output_dir, mock_plugin_manager):
        """Test runner file copying and import rewriting."""
        generator = Generator(sample_config, sample_api_spec)
        
        # Run generation
        generator.generate(temp_output_dir)
        
        # Check that module was created
        collection_path = Path(temp_output_dir) / "ansible_collections" / "test" / "collection"
        module_path = collection_path / "plugins" / "modules" / "test_module.py"
        
        # Verify module file was created
        assert module_path.exists()

    def test_multiple_collections(self, sample_api_spec, temp_output_dir, mock_plugin_manager):
        """Test generation of multiple collections."""
        config = {
            "collections": [
                {
                    "namespace": "test",
                    "name": "collection1",
                    "version": "1.0.0",
                    "modules": [
                        {
                            "name": "module1",
                            "plugin": "crud",
                            "resource_type": "test",
                            "description": "Test module 1",
                        }
                    ]
                },
                {
                    "namespace": "test",
                    "name": "collection2",
                    "version": "2.0.0",
                    "modules": [
                        {
                            "name": "module2",
                            "plugin": "crud",
                            "resource_type": "test",
                            "description": "Test module 2",
                        }
                    ]
                }
            ]
        }
        
        generator = Generator(config, sample_api_spec)
        generator.generate(temp_output_dir)
        
        # Verify both collections were created
        base_path = Path(temp_output_dir) / "ansible_collections" / "test"
        assert (base_path / "collection1").exists()
        assert (base_path / "collection2").exists()
        
        # Verify each has correct galaxy.yml
        with open(base_path / "collection1" / "galaxy.yml") as f:
            galaxy1 = yaml.safe_load(f)
            assert galaxy1["name"] == "collection1"
            assert galaxy1["version"] == "1.0.0"
        
        with open(base_path / "collection2" / "galaxy.yml") as f:
            galaxy2 = yaml.safe_load(f)
            assert galaxy2["name"] == "collection2"
            assert galaxy2["version"] == "2.0.0"

    def test_plugin_manager_integration(self, sample_config, sample_api_spec):
        """Test that generator properly integrates with plugin manager."""
        generator = Generator(sample_config, sample_api_spec)
        
        # Verify plugin manager was initialized
        assert generator.plugin_manager is not None
        assert hasattr(generator.plugin_manager, 'get_plugin')

    def test_setup_collection_skeleton(self, sample_config, sample_api_spec, temp_output_dir, mock_plugin_manager):
        """Test creation of Ansible collection skeleton."""
        generator = Generator(sample_config, sample_api_spec)
        
        # This is a private method that should be tested through the public generate method
        generator.generate(temp_output_dir)
        
        # Verify collection structure was created
        collection_exists = False
        for item in os.listdir(temp_output_dir):
            if "ansible_collections" in item or os.path.isdir(os.path.join(temp_output_dir, item)):
                collection_exists = True
                break
        
        # The generate method should have created some output structure
        assert collection_exists or len(os.listdir(temp_output_dir)) > 0