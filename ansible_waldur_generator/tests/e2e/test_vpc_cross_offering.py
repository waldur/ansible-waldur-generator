import pytest
from ansible_collections.waldur.openstack.plugins.modules import (
    vpc as vpc_module,
)
from ansible_waldur_generator.tests.e2e.conftest import run_module_harness


@pytest.mark.vcr
class TestVPCCrossOffering:
    """
    End-to-end tests for VPC creation across different offerings
    to ensure existence checks are properly scoped by offering.
    """

    # Values taken from user's provided logs
    TEST_DATA = {
        "project": "Demo project",
        "offering_1": "Demo offering 1",
        "offering_2": "Demo offering 2",
        "plan_1": "http://127.0.0.1:8000/api/marketplace-public-offerings/7b219a269da4444b98fe4d32a14a9134/plans/7be89cdf793b45d5b29d59202e28ce6a/",
        "plan_2": "http://127.0.0.1:8000/api/marketplace-public-offerings/6336f2721bdb46b6b191129e1974d689/plans/5db8e0608ebe4b1ca3cf491c67e97662/",
        "resource_name": "test-vpc",
    }

    def test_create_vpc_same_name_different_offerings(self, auth_params):
        """
        Scenario:
        1. Create VPC 'test-vpc' in Offering 1.
        2. Create VPC 'test-vpc' in Offering 2.

        Expected: Both operations should result in a CREATE (changed=True) initially,
        or 'exists' if re-run, but crucially the second one should NOT mistake the
        first one as its own resource.
        """
        # --- Step 1: Create in Offering 1 ---
        params_1 = {
            "state": "present",
            "name": self.TEST_DATA["resource_name"],
            "project": self.TEST_DATA["project"],
            "offering": self.TEST_DATA["offering_1"],
            "plan": self.TEST_DATA["plan_1"],
            "limits": {"cores": 100, "storage": 1000, "ram": 102400},
            "wait": False,
            **auth_params,
        }

        exit_1, fail_1 = run_module_harness(vpc_module, params_1)
        assert fail_1 is None, f"Step 1 failed: {fail_1}"

        # --- Step 2: Create in Offering 2 ---
        params_2 = {
            "state": "present",
            "name": self.TEST_DATA["resource_name"],
            "project": self.TEST_DATA["project"],
            "offering": self.TEST_DATA["offering_2"],
            "plan": self.TEST_DATA["plan_2"],
            "limits": {"cores": 100, "storage": 1000, "ram": 102400},
            "wait": False,
            **auth_params,
        }

        exit_2, fail_2 = run_module_harness(vpc_module, params_2)
        assert fail_2 is None, f"Step 2 failed: {fail_2}"
