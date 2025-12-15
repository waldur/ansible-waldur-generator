import pytest
import shutil
import tempfile
import os
from ansible_waldur_generator.generator import Generator


class TestCrudPluginNoCreate:
    @pytest.fixture
    def temp_output_dir(self):
        """Create a temporary directory for test outputs."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def no_create_config(self):
        return {
            "collections": [
                {
                    "namespace": "test",
                    "name": "no_create",
                    "version": "1.0.0",
                    "modules": [
                        {
                            "name": "module_no_create",
                            "plugin": "crud",
                            "resource_type": "test_resource",
                            "description": "Module without create operation",
                            "operations": {
                                "check": "test_resources_list",
                                "destroy": "test_resources_destroy",
                                "update": "test_resources_update",
                            },
                        }
                    ],
                }
            ]
        }

    @pytest.fixture
    def api_spec(self):
        return {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {
                "/api/test-resources/": {
                    "get": {
                        "operationId": "test_resources_list",
                        "responses": {"200": {"description": "Success"}},
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
                    "delete": {
                        "operationId": "test_resources_destroy",
                        "parameters": [
                            {"name": "uuid", "in": "path", "required": True}
                        ],
                        "responses": {"204": {"description": "No Content"}},
                    },
                    "patch": {
                        "operationId": "test_resources_update",
                        "parameters": [
                            {"name": "uuid", "in": "path", "required": True}
                        ],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"name": {"type": "string"}},
                                    }
                                }
                            }
                        },
                        "responses": {"200": {"description": "Success"}},
                    },
                },
            },
        }

    def test_generate_no_create_module(
        self, no_create_config, api_spec, temp_output_dir
    ):
        generator = Generator(no_create_config, api_spec)
        generator.generate(temp_output_dir)

        # Check module was created
        module_path = os.path.join(
            temp_output_dir,
            "ansible_collections/test/no_create/plugins/modules/module_no_create.py",
        )
        assert os.path.exists(module_path)

        with open(module_path, "r") as f:
            content = f.read()
            # Basic sanity check
            assert "AnsibleModule" in content
            assert "CrudRunner" in content
            # Ensure examples are missing
            assert "Create a new test_resource" not in content
            assert (
                "Remove an existing test_resource" in content
            )  # Destroy IS present in config
            assert "Remove test_resource" in content
