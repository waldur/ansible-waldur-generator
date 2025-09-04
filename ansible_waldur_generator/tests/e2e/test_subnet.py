import pytest

# Import the module under test with a clear alias
from ansible_collections.waldur.openstack.plugins.modules import (
    subnet as subnet_module,
)
from ansible_waldur_generator.tests.e2e.conftest import run_module_harness


@pytest.mark.vcr
class TestSubnetModule:
    """
    Groups all end-to-end tests for the 'subnet' module.
    These tests follow a logical lifecycle: create -> update -> delete.
    """

    # Define consistent test data to be used across the lifecycle tests.
    TEST_DATA = {
        "subnet_name": "E2E-VCR-Test-Subnet-new",
        "network": "waldur-dev-farm-int-net",
        "tenant": "waldur-dev-farm",
        "cidr": "20.0.20.0/24",
    }

    def test_create_subnet_fails(self, auth_params):
        # --- ARRANGE ---
        # Define the user's desired state for creating the subnet.
        user_params = {
            "state": "present",
            "name": self.TEST_DATA["subnet_name"],
            "network": self.TEST_DATA["network"],
            "tenant": self.TEST_DATA["tenant"],
            "cidr": self.TEST_DATA["cidr"],
            "description": "Subnet created by an end-to-end VCR test.",
            "wait": False,
            **auth_params,
        }

        # --- ACT ---
        exit_result, fail_result = run_module_harness(subnet_module, user_params)

        # --- ASSERT ---
        assert (
            fail_result["api_error"]["non_field_errors"][0]
            == "Internal network cannot have more than one subnet."
        )

    def test_create_subnet_exists(self, auth_params):
        """
        Verify that running the 'create' task again with the same parameters
        results in no change, proving idempotency.
        """
        # --- ARRANGE ---
        # Define the user's desired state for creating the subnet.
        user_params = {
            "state": "present",
            "name": self.TEST_DATA["subnet_name"],
            "network": self.TEST_DATA["network"],
            "tenant": self.TEST_DATA["tenant"],
            "cidr": self.TEST_DATA["cidr"],
            "description": "Subnet created by an end-to-end VCR test.",
            "wait": False,
            **auth_params,
        }

        # --- ACT ---
        exit_result, fail_result = run_module_harness(subnet_module, user_params)

        # --- ASSERT ---
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        assert exit_result is not None
        assert exit_result["changed"] is False

    def test_create_subnet_succeeds(self, auth_params):
        """
        Verify that a new subnet can be created successfully under a parent network.
        This is the first step in the resource's lifecycle.
        """
        # --- ARRANGE ---
        # Define the user's desired state for creating the subnet.
        user_params = {
            "state": "present",
            "name": self.TEST_DATA["subnet_name"],
            "network": self.TEST_DATA["network"],
            "tenant": self.TEST_DATA["tenant"],
            "cidr": self.TEST_DATA["cidr"],
            "description": "Subnet created by an end-to-end VCR test.",
            "wait": False,
            **auth_params,
        }

        # --- ACT ---
        exit_result, fail_result = run_module_harness(subnet_module, user_params)

        # --- ASSERT ---
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        assert exit_result is not None
        assert exit_result["changed"] is True
        assert "resource" in exit_result
        assert exit_result["resource"]["name"] == self.TEST_DATA["subnet_name"]
        assert exit_result["resource"]["cidr"] == self.TEST_DATA["cidr"]

    def test_update_subnet(self, auth_params):
        """
        Verify that an existing subnet's description can be updated.
        """
        # --- ARRANGE ---
        new_description = "Updated description for VCR test."
        user_params = {
            "state": "present",
            "name": self.TEST_DATA["subnet_name"],
            "network": self.TEST_DATA["network"],
            "tenant": self.TEST_DATA["tenant"],
            "description": new_description,
            "wait": False,
            **auth_params,
        }

        # --- ACT ---
        exit_result, fail_result = run_module_harness(subnet_module, user_params)

        # --- ASSERT ---
        assert fail_result is None
        assert exit_result is not None
        assert exit_result["changed"] is True
        assert exit_result["resource"]["description"] == new_description

    def test_update_subnet_idempotent(self, auth_params):
        """
        Verify that running the 'update' task again with the same new description
        results in no change.
        """
        # --- ARRANGE ---
        user_params = {
            "state": "present",
            "name": self.TEST_DATA["subnet_name"],
            "network": self.TEST_DATA["network"],
            "tenant": self.TEST_DATA["tenant"],
            "description": "Updated description for VCR test.",
            "wait": False,
            **auth_params,
        }

        # --- ACT ---
        exit_result, fail_result = run_module_harness(subnet_module, user_params)

        # --- ASSERT ---
        assert fail_result is None
        assert exit_result is not None
        assert exit_result["changed"] is False

    def test_delete_subnet(self, auth_params):
        """
        Verify that an existing subnet can be deleted.
        """
        # --- ARRANGE ---
        user_params = {
            "state": "absent",
            "name": self.TEST_DATA["subnet_name"],
            "network": self.TEST_DATA["network"],
            "tenant": self.TEST_DATA["tenant"],
            "wait": False,
            **auth_params,
        }

        # --- ACT ---
        exit_result, fail_result = run_module_harness(subnet_module, user_params)

        # --- ASSERT ---
        assert fail_result is None
        assert exit_result is not None
        assert exit_result["changed"] is True
        assert exit_result["resource"] is None
