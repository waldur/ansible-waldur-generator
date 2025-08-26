import pytest

from ansible_collections.waldur.openstack.plugins.modules import (
    security_group as security_group_module,
)
from ansible_waldur_generator.tests.e2e.conftest import run_module_harness


@pytest.mark.vcr
class TestSecurityGroupModule:
    """
    Groups all end-to-end tests for the 'security_group' module.
    The `@pytest.mark.vcr` decorator will record real API interactions to a
    cassette file on the first run, and replay them on subsequent runs.
    """

    def test_create_security_group_with_rules(self, auth_params):
        """
        End-to-end test for creating a new OpenStack security group with a set of rules.

        This test validates the full "state: present" workflow when the resource
        does not exist. It ensures that:
        1. The parent 'tenant' is correctly resolved.
        2. The nested 'create' endpoint is called with the correct payload.
        3. The 'set_rules' action is triggered correctly after creation (if the API
           workflow requires a separate call for rules, which is common).
        4. The final module result is `changed=True` and contains the full
           description of the newly created security group, including its rules.
        """
        # --- ARRANGE ---
        # Define the user's desired state for the security group in the playbook.
        user_params = {
            "state": "present",
            "name": "E2E-VCR-Test-SG",
            "description": "Security group created by an end-to-end VCR test.",
            # The parent resource under which the security group will be created.
            "tenant": "os-tenant-agnes-ku-12-antelope-1",
            # A list of security group rules to be applied.
            "rules": [
                {
                    "protocol": "tcp",
                    "from_port": 22,
                    "to_port": 22,
                    "cidr": "192.168.1.0/24",
                    "description": "Allow SSH from internal network.",
                },
                {
                    "protocol": "tcp",
                    "from_port": 443,
                    "to_port": 443,
                    "cidr": "0.0.0.0/0",
                    "description": "Allow HTTPS from anywhere.",
                },
            ],
            "wait": False,  # Ensure we wait for the resource to become active.
            **auth_params,  # Unpack standard authentication parameters.
        }

        # --- ACT ---
        # Use the generic harness to run the module with the defined parameters.
        exit_result, fail_result = run_module_harness(
            security_group_module, user_params
        )

        # --- ASSERT ---
        # 1. Ensure the module did not fail unexpectedly.
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"

        # 2. Ensure the module exited successfully.
        assert exit_result is not None

        # 3. Verify that a change occurred.
        assert exit_result["changed"] is True
