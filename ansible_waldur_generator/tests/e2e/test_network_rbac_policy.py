import pytest

# Import the module under test with an alias for clarity.
from ansible_collections.waldur.openstack.plugins.modules import (
    network_rbac_policy as network_rbac_policy_module,
)
from ansible_waldur_generator.tests.e2e.conftest import run_module_harness


@pytest.mark.vcr
class TestNetworkRbacPolicyModule:
    """
    Groups all end-to-end tests for the 'network_rbac_policy' module.
    These tests follow a logical lifecycle: create -> check idempotency -> delete -> check idempotency.
    """

    # Define consistent test data to be used across the lifecycle tests.
    TEST_DATA = {
        "policy_name": "E2E-VCR-Test-Policy",
        "tenant": "waldur-dev-farm",
        "network": "waldur-dev-farm-int-net",
        "target_tenant": "91809",
        "policy_type": "access_as_shared",
    }

    def test_create_policy(self, auth_params):
        """
        Verify that a new RBAC policy can be created successfully.
        This is the first step in the resource's lifecycle.
        """
        # --- ARRANGE ---
        # Define the user's desired state for creating the policy.
        user_params = {
            "state": "present",
            "name": self.TEST_DATA["policy_name"],
            "tenant": self.TEST_DATA["tenant"],
            "network": self.TEST_DATA["network"],
            "target_tenant": self.TEST_DATA["target_tenant"],
            "policy_type": self.TEST_DATA["policy_type"],
            "wait": False,
            **auth_params,  # Unpack standard authentication parameters.
        }

        # --- ACT ---
        # Use the generic harness to run the module with the defined parameters.
        exit_result, fail_result = run_module_harness(
            network_rbac_policy_module, user_params
        )

        # --- ASSERT ---
        # 1. Ensure the module did not fail unexpectedly.
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        # 2. Ensure the module exited successfully.
        assert exit_result is not None
        # 3. Verify that a change occurred, as this is the first creation.
        assert exit_result["changed"] is True
        # 4. Verify that the returned resource state contains the correct data.
        assert "resource" in exit_result

    def test_create_policy_idempotent(self, auth_params):
        """
        Verify that running the 'create' task again with the same parameters
        results in no change, proving idempotency.
        """
        # --- ARRANGE ---
        # The parameters are identical to the 'create' test.
        user_params = {
            "state": "present",
            "name": self.TEST_DATA["policy_name"],
            "tenant": self.TEST_DATA["tenant"],
            "network": self.TEST_DATA["network"],
            "target_tenant": self.TEST_DATA["target_tenant"],
            "policy_type": self.TEST_DATA["policy_type"],
            "wait": False,
            **auth_params,
        }

        # --- ACT ---
        exit_result, fail_result = run_module_harness(
            network_rbac_policy_module, user_params
        )

        # --- ASSERT ---
        assert fail_result is None
        assert exit_result is not None
        # 5. The key assertion: no change should be reported.
        assert exit_result["changed"] is False

    def test_delete_policy(self, auth_params):
        """
        Verify that an existing RBAC policy can be deleted.
        This tests the complex deletion path with two path parameters.
        """
        # --- ARRANGE ---
        # Define the parameters needed to identify and delete the policy.
        user_params = {
            "state": "absent",
            "name": self.TEST_DATA["policy_name"],  # Identifies the policy to delete.
            "tenant": self.TEST_DATA["tenant"],
            "network": self.TEST_DATA["network"],  # Identifies the parent network.
            "wait": False,
            **auth_params,
        }

        # --- ACT ---
        exit_result, fail_result = run_module_harness(
            network_rbac_policy_module, user_params
        )

        # --- ASSERT ---
        assert fail_result is None
        assert exit_result is not None
        # 6. Verify that deleting an existing resource reports a change.
        assert exit_result["changed"] is True
        # 7. A successful deletion should result in a null resource state.
        assert exit_result["resource"] is None

    def test_delete_policy_idempotent(self, auth_params):
        """
        Verify that running the 'delete' task again on a non-existent resource
        results in no change, proving idempotency for the absent state.
        """
        # --- ARRANGE ---
        # The parameters are identical to the 'delete' test.
        user_params = {
            "state": "absent",
            "name": self.TEST_DATA["policy_name"],
            "tenant": self.TEST_DATA["tenant"],
            "network": self.TEST_DATA["network"],
            "wait": False,
            **auth_params,
        }

        # --- ACT ---
        exit_result, fail_result = run_module_harness(
            network_rbac_policy_module, user_params
        )

        # --- ASSERT ---
        assert fail_result is None
        assert exit_result is not None
        # 8. The key assertion: no change should be reported as the resource is already gone.
        assert exit_result["changed"] is False
