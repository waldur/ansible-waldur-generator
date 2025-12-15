import pytest
import shutil
import tempfile
import os
from ansible_waldur_generator.generator import Generator


class TestCrudPluginUpdateExamples:
    @pytest.fixture
    def temp_output_dir(self):
        """Create a temporary directory for test outputs."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def update_action_config(self):
        return {
            "collections": [
                {
                    "namespace": "test",
                    "name": "update_examples",
                    "version": "1.0.0",
                    "modules": [
                        {
                            "name": "module_update_examples",
                            "plugin": "crud",
                            "resource_type": "test_resource",
                            "base_operation_id": "test_resources",
                            "update_config": {
                                "actions": {
                                    "set_rules": {
                                        "operation": "test_resources_set_rules",
                                        "param": "rules",
                                    }
                                }
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
                    "post": {
                        "operationId": "test_resources_create",
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
                    "delete": {
                        "operationId": "test_resources_destroy",
                        "parameters": [
                            {"name": "uuid", "in": "path", "required": True}
                        ],
                        "responses": {"204": {"description": "No Content"}},
                    },
                    "patch": {
                        "operationId": "test_resources_partial_update",
                        "parameters": [
                            {"name": "uuid", "in": "path", "required": True}
                        ],
                        "responses": {"200": {"description": "Success"}},
                    },
                },
                "/api/test-resources/{uuid}/set_rules/": {
                    "post": {
                        "operationId": "test_resources_set_rules",
                        "parameters": [
                            {"name": "uuid", "in": "path", "required": True}
                        ],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "rules": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                            }
                                        },
                                    }
                                }
                            }
                        },
                        "responses": {"200": {"description": "Success"}},
                    },
                },
            },
        }

    def test_generate_update_examples(
        self, update_action_config, api_spec, temp_output_dir
    ):
        generator = Generator(update_action_config, api_spec)
        generator.generate(temp_output_dir)

        module_path = os.path.join(
            temp_output_dir,
            "ansible_collections/test/update_examples/plugins/modules/module_update_examples.py",
        )
        assert os.path.exists(module_path)

        with open(module_path, "r") as f:
            content = f.read()
            # Verify update action example
            # The key is "set_rules", replaced by "set rules"
            assert "Update test_resource - set rules" in content

            # Since update action examples are appended, we should find them
            # The output is YAML, so keys are not quoted like in Python dicts
            assert "rules:" in content
