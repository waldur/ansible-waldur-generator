import pytest

from ansible_collections.waldur.openstack.plugins.modules import (
    volume as volume_module,
)
from ansible_waldur_generator.tests.e2e.conftest import run_module_harness


@pytest.mark.vcr
class TestVolumeModule:
    """Groups all end-to-end tests for the 'volume' module."""

    def test_create_volume(self, auth_params):
        """End-to-end test for creating a new volume."""
        user_params = {
            "state": "present",
            "name": "E2E Test Volume via VCR",
            "project": "E2E Ansible project",
            "offering": "Volume in E2E Ansible tenant",
            "size": 20480,
            "wait": False,
            **auth_params,
        }

        exit_result, fail_result = run_module_harness(volume_module, user_params)

        # ASSERT
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        assert exit_result is not None
        assert exit_result["changed"] is True
        # Note: The response for a create order is the order object, not the final resource
        assert (
            exit_result["commands"][0]["body"]["attributes"]["name"]
            == "E2E Test Volume via VCR"
        )
