import pytest
from ansible_collections.waldur.openstack.plugins.modules import (
    instance as instance_module,
)
from ansible_waldur_generator.tests.e2e.conftest import run_module_harness


@pytest.mark.vcr
class TestInstanceModule:
    """Groups all end-to-end tests for the 'instance' module."""

    def test_create_instance_with_fixed_ports(self, auth_params):
        """End-to-end test for creating instance with ports."""
        user_params = {
            "state": "present",
            "name": "VCR-test",
            "offering": "Virtual machine in waldur-dev",
            "project": "waldur-test",
            "ports": [
                {
                    "subnet": "waldur-dev-sub-net",
                    "fixed_ips": [
                        {
                            "ip_address": "192.168.42.11",
                            "subnet_id": "c807fbd9-f469-4e8e-8d4c-489a4959f433",
                        }
                    ],
                }
            ],
            "flavor": "m1.small",
            "image": "cirros",
            "system_volume_size": "1024",
            "wait": False,
            **auth_params,  # Unpack the auth fixture here
        }

        # ACT: Use the generic harness, passing the instance module object
        exit_result, fail_result = run_module_harness(instance_module, user_params)

        # ASSERT
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        assert exit_result is not None
        assert exit_result["changed"] is True

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
            "release_floating_ips": False,
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
        attributes (like fixed_ips) is idempotent.
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

    def test_instance_port_update_is_performed(self, auth_params):
        user_params = {
            "state": "present",
            "name": "ttu-runner-0e",
            "offering": "Virtual machine in waldur-dev-farm",
            "project": "Self-Service dev infrastructure",
            "tenant": "waldur-dev-farm",
            "ports": [
                {
                    "subnet": "E2E-VCR-Test-Subnet",
                },
                {
                    "subnet": "waldur-dev-farm-sub-net",
                },
            ],
            "wait": False,
            **auth_params,
        }
        # ACT: Use the generic harness, passing the instance module object
        exit_result, fail_result = run_module_harness(instance_module, user_params)

        # ASSERT
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        assert exit_result is not None
        assert exit_result["changed"] is True

    def test_instance_port_fixed_ips_update_is_successful(self, auth_params):
        """
        Verifies that explicitly setting `fixed_ips` on an existing instance port
        triggers a change
        """
        # ARRANGE: Define the desired state for an existing instance.
        user_params = {
            "state": "present",
            "name": "ttu-runner-0e",
            "offering": "Virtual machine in waldur-dev-farm",
            "project": "Self-Service dev infrastructure",
            "tenant": "waldur-dev-farm",
            "ports": [
                {
                    "subnet": "waldur-dev-farm-sub-net",
                    "fixed_ips": [
                        {
                            "ip_address": "192.168.42.150",
                            "subnet_id": "7a8e3178-23c7-4be5-9f84-b526391e6d35",
                        }
                    ],
                }
            ],
            "wait": False,
            **auth_params,
        }

        # ACT: Run the module to perform the update
        update_exit, update_fail = run_module_harness(instance_module, user_params)

        # ASSERT: Verify the change was detected
        assert update_fail is None, (
            f"Module failed unexpectedly during update: {update_fail}"
        )
        assert update_exit is not None
        assert update_exit["changed"] is True, (
            "Module should have detected a change to fixed_ips."
        )
