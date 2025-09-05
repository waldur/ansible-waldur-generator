import pytest
from ansible_collections.waldur.openstack.plugins.modules import (
    instance as instance_module,
)
from ansible_waldur_generator.tests.e2e.conftest import run_module_harness


@pytest.mark.vcr
class TestInstanceModule:
    """Groups all end-to-end tests for the 'instance' module."""

    def test_update_security_groups_skipped(self, auth_params):
        """End-to-end test for updating the security groups of an existing instance."""
        user_params = {
            "state": "present",
            "name": "ttu-runner-0e",
            "offering": "Virtual machine in waldur-dev-farm",
            "project": "Self-Service dev infrastructure",
            "security_groups": ["allow-all", "ssh"],
            "wait": False,
            **auth_params,  # Unpack the auth fixture here
        }

        # ACT: Use the generic harness, passing the instance module object
        exit_result, fail_result = run_module_harness(instance_module, user_params)

        # ASSERT
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        assert exit_result is not None
        assert exit_result["changed"] is False

    def test_update_security_groups_skipped_reorder(self, auth_params):
        """End-to-end test for updating the security groups of an existing instance."""
        user_params = {
            "state": "present",
            "name": "ttu-runner-0e",
            "offering": "Virtual machine in waldur-dev-farm",
            "project": "Self-Service dev infrastructure",
            "security_groups": ["ssh", "allow-all"],
            "wait": False,
            **auth_params,  # Unpack the auth fixture here
        }

        # ACT: Use the generic harness, passing the instance module object
        exit_result, fail_result = run_module_harness(instance_module, user_params)

        # ASSERT
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        assert exit_result is not None
        assert exit_result["changed"] is False

    def test_update_security_groups_performed(self, auth_params):
        """End-to-end test for updating the security groups of an existing instance."""
        user_params = {
            "state": "present",
            "name": "ttu-runner-0e",
            "offering": "Virtual machine in waldur-dev-farm",
            "project": "Self-Service dev infrastructure",
            "security_groups": ["allow-all", "ssh"],
            "wait": False,
            **auth_params,  # Unpack the auth fixture here
        }

        # ACT: Use the generic harness, passing the instance module object
        exit_result, fail_result = run_module_harness(instance_module, user_params)

        # ASSERT
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        assert exit_result is not None
        assert exit_result["changed"] is True

    def test_terminate(self, auth_params):
        """End-to-end test for terminating an existing instance."""
        user_params = {
            "state": "absent",
            "name": "ttu-runner-0e",
            "offering": "Virtual machine in waldur-dev-farm",
            "project": "Self-Service dev infrastructure",
            "wait": False,
            "termination_action": "force_destroy",
            **auth_params,  # Unpack the auth fixture here
        }

        # ACT: Use the generic harness, passing the instance module object
        exit_result, fail_result = run_module_harness(instance_module, user_params)
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        assert exit_result is not None
        assert exit_result["changed"] is True

    def test_instance_port_update_is_idempotent(self, auth_params):
        """
        Validates that updating an instance with a port that omits optional
        attributes (like fixed_ips) is idempotent. The API auto-assigns
        fixed_ips, which could cause a false-positive change detection on
        subsequent runs if the idempotency logic is incorrect.
        """
        user_params = {
            "state": "present",
            "name": "ttu-runner-0e",
            "offering": "Virtual machine in waldur-dev-farm",
            "project": "Self-Service dev infrastructure",
            "tenant": "waldur-dev-farm",
            "ports": [
                {
                    # We intentionally omit 'fixed_ips' here.
                    "subnet": "waldur-dev-farm-sub-net",
                }
            ],
            "wait": False,
            **auth_params,
        }
        # ACT: Use the generic harness, passing the instance module object
        exit_result, fail_result = run_module_harness(instance_module, user_params)

        # ASSERT
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        assert exit_result is not None
        assert exit_result["changed"] is False
