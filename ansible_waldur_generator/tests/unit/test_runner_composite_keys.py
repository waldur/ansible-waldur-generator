import pytest
from unittest.mock import patch
from ansible_waldur_generator.plugins.crud.runner import CrudRunner
from ansible_waldur_generator.helpers import AUTH_FIXTURE


@pytest.fixture
def mock_composite_key_context():
    return {
        "resource_type": "port",
        "check_url": "/api/openstack-ports/",
        "list_path": "/api/openstack-ports/",
        "create_path": "/api/openstack-ports/",
        "destroy_path": "/api/openstack-ports/{uuid}/",
        "update_path": "/api/openstack-ports/{uuid}/",
        "model_param_names": ["name", "network", "subnet", "security_groups"],
        "check_filter_keys": {
            "network": "network_uuid",
            "subnet": "subnet_uuid",
        },
        "resolvers": {
            "network": {
                "url": "/api/openstack-networks/",
            },
            "subnet": {
                "url": "/api/openstack-subnets/",
            },
        },
        "resolver_order": ["network", "subnet"],
        # THE NEW FEATURE
        "composite_keys": ["name", "network", "subnet"],
    }


class TestCompositeKeyRunner:
    @patch("ansible_waldur_generator.plugins.crud.runner.CrudRunner.send_request")
    def test_check_existence_composite_keys(
        self, mock_send_request, mock_ansible_module, mock_composite_key_context
    ):
        """
        Verify that `check_existence` uses composite keys when provided.
        """
        # --- ARRANGE ---
        mock_ansible_module.params = {
            **AUTH_FIXTURE,
            "state": "present",
            "name": "my-port",
            "network": "my-network-name",
            "subnet": "my-subnet-name",
        }

        # Mock resolver responses for network and subnet
        network_obj = {"uuid": "net-uuid", "url": "url/net-uuid/"}
        subnet_obj = {"uuid": "subnet-uuid", "url": "url/subnet-uuid/"}

        # Mock resource response (found)
        found_resource = {"uuid": "port-uuid", "name": "my-port"}

        mock_send_request.side_effect = [
            ([network_obj], 200),  # Resolve network
            ([subnet_obj], 200),  # Resolve subnet
            ([found_resource], 200),  # The actual existence check call
        ]

        # --- ACT ---
        runner = CrudRunner(mock_ansible_module, mock_composite_key_context)
        runner.check_existence()

        # --- ASSERT ---
        # Verify the existence check call was made with the correct query params
        # "name" -> "name" (default mappings)
        # "network" -> "network_uuid" (from check_filter_keys + resolver)
        # "subnet" -> "subnet_uuid" (from check_filter_keys + resolver)

        expected_query = {
            "name": "my-port",
            "network_uuid": "net-uuid",
            "subnet_uuid": "subnet-uuid",
        }

        # Find the call to check_url
        check_call = mock_send_request.call_args_list[-1]
        args, kwargs = check_call
        assert args[1] == "/api/openstack-ports/"
        assert kwargs["query_params"] == expected_query
        assert runner.resource == found_resource

    @patch("ansible_waldur_generator.plugins.crud.runner.CrudRunner.send_request")
    def test_check_existence_composite_keys_missing_param(
        self, mock_send_request, mock_ansible_module, mock_composite_key_context
    ):
        """
        Verify that `check_existence` fails if a composite key part is missing.
        """
        # --- ARRANGE ---
        mock_ansible_module.params = {
            **AUTH_FIXTURE,
            "state": "present",
            "name": "my-port",
            # "network" is missing!
            "subnet": "my-subnet-name",
        }
        mock_ansible_module.fail_json.side_effect = Exception("Ansible Fail")

        # --- ACT ---
        with pytest.raises(Exception, match="Ansible Fail"):
            runner = CrudRunner(mock_ansible_module, mock_composite_key_context)
            runner.check_existence()

        # --- ASSERT ---
        mock_ansible_module.fail_json.assert_called_once()
        msg = mock_ansible_module.fail_json.call_args[1]["msg"]
        assert "Missing required parameter for composite key" in msg
        assert "network" in msg
