# In ansible_waldur_generator/tests/unit/test_order_runner.py

import pytest
from unittest.mock import patch

# The class we are testing
from ansible_waldur_generator.helpers import AUTH_FIXTURE
from ansible_waldur_generator.plugins.order.runner import OrderRunner


@pytest.fixture
def mock_instance_runner_context():
    """
    A pytest fixture providing a realistic, mocked context dictionary for a full-featured
    OpenStack instance module. This context is crucial as it drives the runner's behavior.

    It includes:
    - API endpoints for checking, updating, and deleting.
    - Context filters (`check_filter_keys`) to test dependency-aware lookups.
    - Updatable fields for both simple (PATCH) and complex (POST action) updates.
    - A rich set of resolvers, including some with `filter_by` dependencies.
    - The `resolver_order`, which is the topologically sorted list of resolvers
      that the runner now uses for its dependency-aware logic.
    """
    context = {
        "resource_type": "OpenStack instance",
        "check_url": "/api/openstack-instances/",
        "check_filter_keys": {"project": "project_uuid"},
        "update_path": "/api/openstack-instances/{uuid}/",
        "update_fields": ["description", "name"],
        "attribute_param_names": [
            "flavor",
            "image",
            "security_groups",
            "system_volume_size",
            "user_data",
            "ports",
            "floating_ips",
            "ssh_public_key",
            "availability_zone",
        ],
        "update_actions": {
            "update_ports": {
                "path": "/api/openstack-instances/{uuid}/update_ports/",
                "param": "ports",
                "compare_key": "ports",
                "idempotency_keys": ["subnet", "fixed_ips"],
                "wrap_in_object": True,
            },
            "update_security_groups": {
                "path": "/api/openstack-instances/{uuid}/update_security_groups/",
                "param": "security_groups",
                "compare_key": "security_groups",
                "idempotency_keys": [],
                "wrap_in_object": True,
            },
        },
        "resolvers": {
            "project": {
                "url": "/api/projects/",
                "error_message": "Project '{value}' not found.",
                "is_list": False,
                "filter_by": [],
            },
            "offering": {
                "url": "/api/marketplace-public-offerings/",
                "error_message": "Offering '{value}' not found.",
                "is_list": False,
                "filter_by": [],
            },
            "flavor": {
                "url": "/api/openstack-flavors/",
                "error_message": "Flavor '{value}' not found.",
                "is_list": False,
                "filter_by": [
                    {
                        "source_param": "offering",
                        "source_key": "scope_uuid",
                        "target_key": "tenant_uuid",
                    }
                ],
            },
            "image": {
                "url": "/api/openstack-images/",
                "error_message": "Image '{value}' not found.",
                "is_list": False,
                "filter_by": [
                    {
                        "source_param": "offering",
                        "source_key": "scope_uuid",
                        "target_key": "tenant_uuid",
                    }
                ],
            },
            "security_groups": {
                "url": "/api/openstack-security-groups/",
                "error_message": "Security group '{value}' not found.",
                "is_list": True,
                "filter_by": [
                    {
                        "source_param": "offering",
                        "source_key": "scope_uuid",
                        "target_key": "tenant_uuid",
                    }
                ],
                "list_item_keys": {"create": "url", "update_action": None},
            },
            "subnet": {
                "url": "/api/openstack-subnets/",
                "error_message": "Subnet '{value}' not found.",
                "is_list": False,
                "filter_by": [
                    {
                        "source_param": "offering",
                        "source_key": "scope_uuid",
                        "target_key": "tenant_uuid",
                    }
                ],
            },
            "ssh_public_key": {
                "url": "/api/ssh-keys/",
                "error_message": "SSH key '{value}' not found.",
                "is_list": False,
                "filter_by": [],
            },
        },
        "termination_attributes_map": {
            "termination_action": "action",
            "delete_volumes": "delete_volumes",
            "release_floating_ips": "release_floating_ips",
        },
        "resolver_order": [
            "project",
            "offering",
            "ssh_public_key",
            "flavor",
            "image",
            "security_groups",
            "subnet",
        ],
    }
    return context


class TestOrderRunner:
    """
    A comprehensive test suite for the OrderRunner logic. These tests now use a
    robust, order-independent mocking strategy for API calls, making them more
    resilient to refactoring of the runner's internal logic.
    """

    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner.send_request")
    def test_create_instance_with_full_payload(
        self, mocksend_request, mock_ansible_module, mock_instance_runner_context
    ):
        """
        Tests the full payload creation for a complex instance, validating that all
        resolvers (top-level, dependent, list-based, and nested) work together
        to build the correct final API request.
        """
        # --- ARRANGE: Define user parameters and final state. ---
        mock_ansible_module.params = {
            **AUTH_FIXTURE,
            "state": "present",
            "wait": True,
            "interval": 1,
            "timeout": 1,
            "name": "prod-web-vm-01",
            "project": "Production Project",
            "offering": "Premium Instance Offering",
            "plan": "http://api.com/api/plans/plan-uuid/",
            "limits": {"cpu": 8, "ram": 16384},
            "flavor": "large-flavor",
            "image": "ubuntu-22.04-image",
            "security_groups": ["web-access-sg", "ssh-internal-sg"],
            "system_volume_size": 100,
            "ports": [
                {
                    "subnet": "private-network-subnet",
                    "fixed_ips": [{"ip_address": "10.0.1.50"}],
                }
            ],
            "floating_ips": [{"subnet": "public-floating-ip-subnet"}],
            "ssh_public_key": "admin-ssh-key",
        }
        final_resource_state = {
            "name": "prod-web-vm-01",
            "state": "OK",
            "uuid": "final-vm-uuid-123",
        }

        # --- ARRANGE: Define the state of the world via a mock API router. ---
        def api_router(method, path, query_params=None, **kwargs):
            """This function acts as a router for all mocked API calls."""
            query_params = query_params or {}

            # Route GET requests based on path and query parameters
            if method == "GET":
                if (
                    path == "/api/projects/"
                    and query_params.get("name_exact") == "Production Project"
                ):
                    return (
                        [
                            {
                                "url": "http://api.com/api/projects/proj-prod-uuid/",
                                "uuid": "proj-prod-uuid",
                            }
                        ],
                        200,
                    )
                if (
                    path == "/api/openstack-instances/"
                    and query_params.get("project_uuid") == "proj-prod-uuid"
                ):
                    # For the final re-fetch, return the completed resource. Otherwise, it doesn't exist.
                    if any(
                        c.args[0] == "POST" and c.args[1] == "/api/marketplace-orders/"
                        for c in mocksend_request.call_args_list
                    ):
                        return ([final_resource_state], 200)
                    return ([], 200)  # Initial existence check finds nothing
                if (
                    path == "/api/marketplace-public-offerings/"
                    and query_params.get("name_exact") == "Premium Instance Offering"
                ):
                    return (
                        [
                            {
                                "url": "http://api.com/api/offerings/off-prem-uuid/",
                                "scope_uuid": "tenant-prod-123",
                            }
                        ],
                        200,
                    )
                if (
                    path == "/api/openstack-flavors/"
                    and query_params.get("name_exact") == "large-flavor"
                ):
                    return (
                        [{"url": "http://api.com/api/flavors/flavor-large-uuid/"}],
                        200,
                    )
                if (
                    path == "/api/openstack-images/"
                    and query_params.get("name_exact") == "ubuntu-22.04-image"
                ):
                    return (
                        [{"url": "http://api.com/api/images/img-ubuntu-uuid/"}],
                        200,
                    )
                if path == "/api/openstack-security-groups/":
                    if query_params.get("name_exact") == "web-access-sg":
                        return (
                            [
                                {
                                    "url": "http://api.com/api/security-groups/sg-web-uuid/"
                                }
                            ],
                            200,
                        )
                    if query_params.get("name_exact") == "ssh-internal-sg":
                        return (
                            [
                                {
                                    "url": "http://api.com/api/security-groups/sg-ssh-uuid/"
                                }
                            ],
                            200,
                        )
                if path == "/api/openstack-subnets/":
                    if query_params.get("name_exact") == "private-network-subnet":
                        return (
                            [
                                {
                                    "url": "http://api.com/api/subnets/subnet-private-uuid/"
                                }
                            ],
                            200,
                        )
                    if query_params.get("name_exact") == "public-floating-ip-subnet":
                        return (
                            [{"url": "http://api.com/api/subnets/subnet-public-uuid/"}],
                            200,
                        )
                if (
                    path == "/api/ssh-keys/"
                    and query_params.get("name_exact") == "admin-ssh-key"
                ):
                    return (
                        [{"url": "http://api.com/api/ssh-keys/key-admin-uuid/"}],
                        200,
                    )
                if path == "/api/marketplace-orders/{uuid}/":  # Polling call
                    return ({"state": "done"}, 200)

            # Route POST requests for order submission
            if method == "POST" and path == "/api/marketplace-orders/":
                return ({"uuid": "order-xyz-789"}, 200)

            # Fallback for any unexpected API call
            raise Exception(
                f"Unexpected API call in mock router: {method} {path} {query_params}"
            )

        mocksend_request.side_effect = api_router

        # --- ACT ---
        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        # --- ASSERT: Verify the final state and the commands generated. ---
        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True,
            resource=final_resource_state,
            commands=[
                {
                    "method": "POST",
                    "url": "https://waldur.example.com/api/marketplace-orders/",
                    "description": "Create OpenStack instance via marketplace order",
                    "body": {
                        "project": "http://api.com/api/projects/proj-prod-uuid/",
                        "offering": "http://api.com/api/offerings/off-prem-uuid/",
                        "attributes": {
                            "name": "prod-web-vm-01",
                            "flavor": "http://api.com/api/flavors/flavor-large-uuid/",
                            "image": "http://api.com/api/images/img-ubuntu-uuid/",
                            "security_groups": [
                                {
                                    "url": "http://api.com/api/security-groups/sg-web-uuid/"
                                },
                                {
                                    "url": "http://api.com/api/security-groups/sg-ssh-uuid/"
                                },
                            ],
                            "system_volume_size": 100,
                            "ports": [
                                {
                                    "subnet": "http://api.com/api/subnets/subnet-private-uuid/",
                                    "fixed_ips": [{"ip_address": "10.0.1.50"}],
                                }
                            ],
                            "floating_ips": [
                                {
                                    "subnet": "http://api.com/api/subnets/subnet-public-uuid/"
                                }
                            ],
                            "ssh_public_key": "http://api.com/api/ssh-keys/key-admin-uuid/",
                        },
                        "accepting_terms_of_service": True,
                        "plan": "http://api.com/api/plans/plan-uuid/",
                        "limits": {"cpu": 8, "ram": 16384},
                    },
                }
            ],
        )

    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner.send_request")
    def test_resource_exists_no_change(
        self, mocksend_request, mock_ansible_module, mock_instance_runner_context
    ):
        """Tests idempotency: if the resource exists and its updatable fields match, no changes should be made."""
        mock_ansible_module.params = {
            **AUTH_FIXTURE,
            "state": "present",
            "name": "existing-vm",
            "project": "Cloud Project",
            "description": "current description",
        }
        existing_resource = {
            "name": "existing-vm",
            "uuid": "vm-uuid-123",
            "description": "current description",
            "state": "OK",
        }

        def api_router(method, path, query_params=None, **kwargs):
            if method == "GET" and path == "/api/projects/":
                return (
                    [
                        {
                            "url": "http://api.com/api/projects/proj-uuid/",
                            "uuid": "proj-uuid",
                        }
                    ],
                    200,
                )
            if method == "GET" and path == "/api/openstack-instances/":
                return ([existing_resource], 200)
            return (None, 404)

        mocksend_request.side_effect = api_router

        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        mock_ansible_module.exit_json.assert_called_once_with(
            changed=False, commands=[], resource=existing_resource
        )

    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner.send_request")
    def test_update_existing_resource(
        self, mocksend_request, mock_ansible_module, mock_instance_runner_context
    ):
        """Tests that a change to a simple updatable field (like 'description') triggers a PATCH request."""
        mock_ansible_module.params = {
            **AUTH_FIXTURE,
            "state": "present",
            "name": "vm-to-update",
            "project": "Cloud Project",
            "description": "a new description",
        }
        existing_resource = {
            "name": "vm-to-update",
            "uuid": "vm-uuid-456",
            "description": "old description",
        }
        updated_resource = {**existing_resource, "description": "a new description"}

        def api_router(method, path, **kwargs):
            if method == "GET" and "/api/projects/" in path:
                return (
                    [
                        {
                            "url": "http://api.com/api/projects/proj-uuid/",
                            "uuid": "proj-uuid",
                        }
                    ],
                    200,
                )
            if method == "GET" and "/api/openstack-instances/" in path:
                return ([existing_resource], 200)
            if method == "PATCH" and path == "/api/openstack-instances/{uuid}/":
                return (updated_resource, 200)
            return (None, 404)

        mocksend_request.side_effect = api_router

        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True,
            resource=updated_resource,
            commands=[
                {
                    "method": "PATCH",
                    "url": "https://waldur.example.com/api/openstack-instances/vm-uuid-456/",
                    "description": "Update attributes of OpenStack instance",
                    "body": {"description": "a new description"},
                }
            ],
        )

    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner.send_request")
    def test_delete_existing_resource(
        self, mocksend_request, mock_ansible_module, mock_instance_runner_context
    ):
        """Tests that `state: absent` correctly triggers a termination call when the resource exists."""
        mock_ansible_module.params = {
            **AUTH_FIXTURE,
            "state": "absent",
            "name": "vm-to-delete",
            "project": "Cloud Project",
        }
        existing_resource = {
            "name": "vm-to-delete",
            "marketplace_resource_uuid": "mkt-res-uuid-789",
        }

        def api_router(method, path, **kwargs):
            if method == "GET" and "/api/projects/" in path:
                return (
                    [
                        {
                            "url": "http://api.com/api/projects/proj-uuid/",
                            "uuid": "proj-uuid",
                        }
                    ],
                    200,
                )
            if method == "GET" and "/api/openstack-instances/" in path:
                return ([existing_resource], 200)
            if method == "POST" and "/terminate/" in path:
                return (None, 202)
            return (None, 404)

        mocksend_request.side_effect = api_router

        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True,
            resource=None,
            commands=[
                {
                    "method": "POST",
                    "url": "https://waldur.example.com/api/marketplace-resources/mkt-res-uuid-789/terminate/",
                    "description": "Terminate OpenStack instance 'vm-to-delete'",
                }
            ],
        )

    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner.send_request")
    def test_check_mode_predicts_creation(
        self, mocksend_request, mock_ansible_module, mock_instance_runner_context
    ):
        """Tests that check mode correctly predicts creation without making modifying API calls."""
        mock_ansible_module.check_mode = True
        mock_ansible_module.params = {
            **AUTH_FIXTURE,
            "state": "present",
            "name": "new-vm-in-check-mode",
            "project": "Cloud Project",
        }

        def api_router(method, path, **kwargs):
            if method == "GET" and "/api/projects/" in path:
                return (
                    [
                        {
                            "url": "http://api.com/api/projects/proj-uuid/",
                            "uuid": "proj-uuid",
                        }
                    ],
                    200,
                )
            if method == "GET" and "/api/openstack-instances/" in path:
                return ([], 200)  # Finds no resource
            return (None, 404)

        mocksend_request.side_effect = api_router

        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True, commands=[], resource=None
        )
        assert mocksend_request.call_count == 2  # Only read-only existence check calls.

    @patch("ansible_waldur_generator.plugins.order.runner.OrderRunner.send_request")
    def test_delete_resource_with_all_termination_attributes(
        self, mocksend_request, mock_ansible_module, mock_instance_runner_context
    ):
        """Tests that `state: absent` correctly includes all provided termination attributes in the payload."""
        mock_ansible_module.params = {
            **AUTH_FIXTURE,
            "state": "absent",
            "name": "vm-to-force-delete",
            "project": "Cloud Project",
            "termination_action": "force_destroy",
            "delete_volumes": True,
            "release_floating_ips": True,
        }
        existing_resource = {
            "name": "vm-to-force-delete",
            "marketplace_resource_uuid": "mkt-res-uuid-123",
        }

        def api_router(method, path, **kwargs):
            if method == "GET" and "/api/projects/" in path:
                return (
                    [
                        {
                            "url": "http://api.com/api/projects/proj-uuid/",
                            "uuid": "proj-uuid",
                        }
                    ],
                    200,
                )
            if method == "GET" and "/api/openstack-instances/" in path:
                return ([existing_resource], 200)
            if method == "POST" and "/terminate/" in path:
                return (None, 202)
            return (None, 404)

        mocksend_request.side_effect = api_router

        runner = OrderRunner(mock_ansible_module, mock_instance_runner_context)
        runner.run()

        mock_ansible_module.exit_json.assert_called_once_with(
            changed=True,
            resource=None,
            commands=[
                {
                    "method": "POST",
                    "url": "https://waldur.example.com/api/marketplace-resources/mkt-res-uuid-123/terminate/",
                    "description": "Terminate OpenStack instance 'vm-to-force-delete'",
                    "body": {
                        "attributes": {
                            "action": "force_destroy",
                            "delete_volumes": True,
                            "release_floating_ips": True,
                        }
                    },
                }
            ],
        )
