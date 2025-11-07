import pytest

from ansible_collections.waldur.openstack.plugins.modules import (
    volume as volume_module,
)
from ansible_waldur_generator.tests.e2e.conftest import run_module_harness


@pytest.mark.vcr
class TestVolumeModule:
    """Groups all end-to-end tests for the 'volume' module."""

    # Common data for tests to ensure consistency
    TEST_DATA = {
        "project": "E2E Ansible project",
        "offering": "Volume in E2E Ansible tenant",
        "volume_name": "E2E Test Volume via VCR",
    }

    def test_create_volume(self, auth_params):
        """End-to-end test for creating a new volume."""
        user_params = {
            "state": "present",
            "name": self.TEST_DATA["volume_name"],
            "project": self.TEST_DATA["project"],
            "offering": self.TEST_DATA["offering"],
            "size": 20,  # 20 GiB
            "wait": False,
            **auth_params,
        }

        exit_result, fail_result = run_module_harness(volume_module, user_params)

        # ASSERT
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        assert exit_result is not None
        assert exit_result["changed"] is True
        assert (
            exit_result["commands"][0]["body"]["attributes"]["name"]
            == self.TEST_DATA["volume_name"]
        )
        assert (
            exit_result["commands"][0]["body"]["attributes"]["size"] == 20480
        )  # 20 GiB in MiB

    def test_extend_volume(self, auth_params):
        """Test extending an existing volume using the 'size' parameter, which maps to 'disk_size'."""
        user_params = {
            "state": "present",
            "name": self.TEST_DATA["volume_name"],
            "project": self.TEST_DATA["project"],
            "offering": self.TEST_DATA["offering"],
            "size": 30720,
            "wait": False,
            **auth_params,
        }

        exit_result, fail_result = run_module_harness(volume_module, user_params)

        # ASSERT
        assert fail_result is None
        assert exit_result is not None
        assert exit_result["changed"] is True
        # Verify the command sent to the API used the mapped key 'disk_size'
        command = exit_result["commands"][0]
        assert command["method"] == "POST"
        assert "/extend/" in command["url"]
        assert command["body"] == {"disk_size": 30720}

    def test_retype_volume(self, auth_params):
        """Test retyping an existing volume."""
        user_params = {
            "state": "present",
            "name": self.TEST_DATA["volume_name"],
            "project": self.TEST_DATA["project"],
            "offering": self.TEST_DATA["offering"],
            "type": "ultra-high-iops",
            "wait": False,
            **auth_params,
        }

        exit_result, fail_result = run_module_harness(volume_module, user_params)

        # ASSERT
        assert fail_result is None
        assert exit_result is not None
        assert exit_result["changed"] is True
        command = exit_result["commands"][0]
        assert command["method"] == "POST"
        assert "/retype/" in command["url"]
