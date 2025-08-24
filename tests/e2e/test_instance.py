import pytest
from ansible_collections.waldur.openstack.plugins.modules import (
    instance as instance_module,
)
from tests.e2e.conftest import run_module_harness


@pytest.mark.vcr
class TestInstanceModule:
    """Groups all end-to-end tests for the 'instance' module."""

    def test_update_security_groups(self, auth_params):
        """End-to-end test for updating the security groups of an existing instance."""
        user_params = {
            "state": "present",
            "name": "E2E-S-IAAB33-1",
            "offering": "Virtual machine in E2E Ansible tenant",
            "project": "E2E Ansible project",
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

        final_sg_names = [
            sg["name"] for sg in exit_result["resource"]["security_groups"]
        ]
        assert "allow-all" in final_sg_names
        assert "ssh" in final_sg_names
        assert len(final_sg_names) == 2

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
