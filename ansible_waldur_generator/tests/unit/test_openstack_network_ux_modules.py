"""Unit tests for the OpenStack network-UX uplift Ansible exposures.

These tests verify that the per-MR additions to
``waldur-mastermind/ansible-generator-config.yaml`` generate the
expected modules with the right plugin shape and parameter wiring.
They use a minimal in-memory OpenAPI spec so the tests do not require
the full mastermind schema to run.

Each scenario corresponds to one upstream mastermind MR:
- T7 (WAL-9977): port.update.actions.set_allowed_address_pairs
- T6 (WAL-9976): instance_action.actions += diagnose_connectivity
"""

import os
import shutil
import tempfile

import pytest

from ansible_waldur_generator.generator import Generator


@pytest.fixture
def temp_output_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _module_path(out_dir: str, namespace: str, name: str, module: str) -> str:
    return os.path.join(
        out_dir,
        "ansible_collections",
        namespace,
        name,
        "plugins",
        "modules",
        f"{module}.py",
    )


# ---------------------------------------------------------------------------
# T7 — Port.set_allowed_address_pairs
# ---------------------------------------------------------------------------


@pytest.fixture
def aap_api_spec():
    """Minimal OpenAPI surface a port crud module needs to compile."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/api/openstack-ports/": {
                "get": {
                    "operationId": "openstack_ports_list",
                    "responses": {"200": {"description": "ok"}},
                },
                "post": {
                    "operationId": "openstack_ports_create",
                    "responses": {"201": {"description": "ok"}},
                },
            },
            "/api/openstack-ports/{uuid}/": {
                "get": {
                    "operationId": "openstack_ports_retrieve",
                    "parameters": [{"name": "uuid", "in": "path", "required": True}],
                    "responses": {"200": {"description": "ok"}},
                },
                "delete": {
                    "operationId": "openstack_ports_destroy",
                    "parameters": [{"name": "uuid", "in": "path", "required": True}],
                    "responses": {"204": {"description": "ok"}},
                },
            },
            "/api/openstack-ports/{uuid}/set_allowed_address_pairs/": {
                "post": {
                    "operationId": "openstack_ports_set_allowed_address_pairs",
                    "parameters": [{"name": "uuid", "in": "path", "required": True}],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "allowed_address_pairs": {
                                            "type": "array",
                                            "items": {"type": "object"},
                                        }
                                    },
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "ok"}},
                }
            },
        },
    }


@pytest.fixture
def aap_config():
    return {
        "collections": [
            {
                "namespace": "waldur",
                "name": "openstack",
                "version": "1.0.0",
                "modules": [
                    {
                        "name": "port",
                        "plugin": "crud",
                        "resource_type": "OpenStack port",
                        "base_operation_id": "openstack_ports",
                        "update_config": {
                            "actions": {
                                "set_allowed_address_pairs": {
                                    "operation": "openstack_ports_set_allowed_address_pairs",
                                    "param": "allowed_address_pairs",
                                    "compare_key": "allowed_address_pairs",
                                }
                            }
                        },
                    }
                ],
            }
        ]
    }


class TestPortSetAllowedAddressPairs:
    def test_port_module_compiles_with_aap_action(
        self, aap_config, aap_api_spec, temp_output_dir
    ):
        Generator(aap_config, aap_api_spec).generate(temp_output_dir)
        path = _module_path(temp_output_dir, "waldur", "openstack", "port")
        assert os.path.exists(path), f"port module not generated at {path}"
        content = open(path).read()
        # The user-facing parameter must be exposed in the ARGUMENT_SPEC.
        assert "allowed_address_pairs" in content
        # The action URL must be wired into RUNNER_CONTEXT.
        assert "/api/openstack-ports/{uuid}/set_allowed_address_pairs/" in content


# ---------------------------------------------------------------------------
# T6 — Instance.diagnose_connectivity
# ---------------------------------------------------------------------------


@pytest.fixture
def diagnose_api_spec():
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/api/openstack-instances/": {
                "get": {
                    "operationId": "openstack_instances_list",
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/api/openstack-instances/{uuid}/": {
                "get": {
                    "operationId": "openstack_instances_retrieve",
                    "parameters": [{"name": "uuid", "in": "path", "required": True}],
                    "responses": {"200": {"description": "ok"}},
                }
            },
            "/api/openstack-instances/{uuid}/diagnose_connectivity/": {
                "post": {
                    "operationId": "openstack_instances_diagnose_connectivity",
                    "parameters": [{"name": "uuid", "in": "path", "required": True}],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"target": {"type": "string"}},
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "ok"}},
                }
            },
        },
    }


@pytest.fixture
def diagnose_config():
    return {
        "collections": [
            {
                "namespace": "waldur",
                "name": "openstack",
                "version": "1.0.0",
                "modules": [
                    {
                        "name": "instance_action",
                        "plugin": "actions",
                        "resource_type": "OpenStack instance",
                        "base_operation_id": "openstack_instances",
                        "actions": ["diagnose_connectivity"],
                    }
                ],
            }
        ]
    }


class TestInstanceDiagnoseConnectivity:
    def test_instance_action_module_includes_diagnose(
        self, diagnose_config, diagnose_api_spec, temp_output_dir
    ):
        Generator(diagnose_config, diagnose_api_spec).generate(temp_output_dir)
        path = _module_path(temp_output_dir, "waldur", "openstack", "instance_action")
        assert os.path.exists(path)
        content = open(path).read()
        # The action name appears in the choices list and RUNNER_CONTEXT.
        assert "diagnose_connectivity" in content
        # The action URL must be wired into RUNNER_CONTEXT.
        assert "/api/openstack-instances/{uuid}/diagnose_connectivity/" in content
