import pytest

# Import the module under test with a clear alias
from ansible_collections.waldur.openstack.plugins.modules import (
    port as port_module,
)
from ansible_waldur_generator.tests.e2e.conftest import run_module_harness


@pytest.mark.vcr
class TestPortModule:
    """
    Groups all end-to-end tests for the 'port' module.
    """

    # Define consistent test data to be used across the lifecycle tests.
    TEST_DATA = {
        "port_name": "E2E-VCR-Test-port-new",
        "network": "terraform-e2e-vpc-int-net",
        "tenant": "terraform-e2e-vpc_TtR",
        "subnet": "terraform-e2e-vpc-sub-net",
    }

    def test_create_port_succeeds(self, auth_params):
        """
        Verify that a new port can be created successfully under a parent network.
        This is the first step in the resource's lifecycle.
        """
        # --- ARRANGE ---
        # Define the user's desired state for creating the port.
        user_params = {
            "state": "present",
            "name": self.TEST_DATA["port_name"],
            "network": self.TEST_DATA["network"],
            "tenant": self.TEST_DATA["tenant"],
            "description": "Port created by an end-to-end VCR test.",
            "wait": True,
            **auth_params,
        }

        # --- ACT ---
        exit_result, fail_result = run_module_harness(port_module, user_params)

        # --- ASSERT ---
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        assert exit_result is not None
        assert exit_result["changed"] is True
        assert "resource" in exit_result
        assert exit_result["resource"]["name"] == self.TEST_DATA["port_name"]


    def test_update_security_groups(self, auth_params):
        # --- ARRANGE ---
        # Define the user's desired state for creating the port.
        user_params = {
            "state": "present",
            "name": self.TEST_DATA["port_name"],
            "network": self.TEST_DATA["network"],
            "tenant": self.TEST_DATA["tenant"],
            "description": "Port created by an end-to-end VCR test.",
            "security_groups": ["ssh"],
            "wait": True,
            **auth_params,
        }

        # --- ACT ---
        exit_result, fail_result = run_module_harness(port_module, user_params)

        # --- ASSERT ---
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        assert exit_result is not None
        assert exit_result["changed"] is True

    def test_update_security_groups_idempotence(self, auth_params):
        # --- ARRANGE ---
        # Define the user's desired state for creating the port.
        user_params = {
            "state": "present",
            "name": self.TEST_DATA["port_name"],
            "network": self.TEST_DATA["network"],
            "tenant": self.TEST_DATA["tenant"],
            "description": "Port created by an end-to-end VCR test.",
            "security_groups": ["ssh"],
            "wait": True,
            **auth_params,
        }

        # --- ACT ---
        exit_result, fail_result = run_module_harness(port_module, user_params)

        # --- ASSERT ---
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        assert exit_result is not None
        assert exit_result["changed"] is False

    def test_update_fixed_ips(self, auth_params):
        # --- ARRANGE ---
        # Define the user's desired state.
        user_params = {
            "state": "present",
            "name": self.TEST_DATA["port_name"],
            "network": self.TEST_DATA["network"],
            "tenant": self.TEST_DATA["tenant"],
            "fixed_ips": [
                {
                    "subnet": self.TEST_DATA["subnet"],
                    "ip_address": "192.168.42.50",
                }
            ],
            "wait": True,
            **auth_params,
        }

        # --- ACT ---
        exit_result, fail_result = run_module_harness(port_module, user_params)

        # --- ASSERT ---
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        assert exit_result is not None
        assert exit_result["changed"] is True

    def test_update_fixed_ips_idempotence(self, auth_params):
        # --- ARRANGE ---
        user_params = {
            "state": "present",
            "name": self.TEST_DATA["port_name"],
            "network": self.TEST_DATA["network"],
            "tenant": self.TEST_DATA["tenant"],
            "fixed_ips": [
                {
                    "subnet": self.TEST_DATA["subnet"],
                    "ip_address": "192.168.42.50",
                }
            ],
            "wait": True,
            **auth_params,
        }

        # --- ACT ---
        exit_result, fail_result = run_module_harness(port_module, user_params)

        # --- ASSERT ---
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        assert exit_result is not None
        assert exit_result["changed"] is False

    def test_z_delete_port(self, auth_params):
        """
        Verify that an existing port can be deleted.
        """
        # --- ARRANGE ---
        user_params = {
            "state": "absent",
            "name": self.TEST_DATA["port_name"],
            "network": self.TEST_DATA["network"],
            "tenant": self.TEST_DATA["tenant"],
            "wait": True,
            **auth_params,
        }

        # --- ACT ---
        exit_result, fail_result = run_module_harness(port_module, user_params)

        # --- ASSERT ---
        assert fail_result is None
        assert exit_result is not None
        assert exit_result["changed"] is True
        assert exit_result["resource"] is None
