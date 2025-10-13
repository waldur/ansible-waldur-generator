import pytest

# Import the module under test with a clear alias
from ansible_collections.waldur.openstack.plugins.modules import (
    volume_attachment as volume_attachment_module,
)
from ansible_waldur_generator.tests.e2e.conftest import run_module_harness


@pytest.mark.vcr
class TestVolumeAttachmentModule:
    """
    Groups all end-to-end tests for the 'volume_attachment' module.
    These tests follow a logical lifecycle for the attachment relationship.
    """

    # Define consistent test data to be used across the lifecycle tests.
    TEST_DATA = {
        "volume": "Test-data",
        "instance": "ThesisAnalyzer",
        "project": "Thesis Analyzer",
        "tenant": "Thesis Analyzer VM",
    }

    def test_attach_volume(self, auth_params):
        """
        Verify that a volume can be successfully attached to an instance.
        """
        # --- ARRANGE ---
        # Define the user's desired state for attaching the volume.
        user_params = {
            "state": "present",
            "volume": self.TEST_DATA["volume"],
            "instance": self.TEST_DATA["instance"],
            "project": self.TEST_DATA["project"],  # Context for resolving resources
            "tenant": self.TEST_DATA["tenant"],
            "device": "/dev/vdf",  # Optional parameter for the link operation
            **auth_params,
        }

        # --- ACT ---
        # Use the generic harness to run the module with the defined parameters.
        exit_result, fail_result = run_module_harness(
            volume_attachment_module, user_params
        )

        # --- ASSERT ---
        # 1. Ensure the module did not fail unexpectedly.
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        # 2. Ensure the module exited successfully.
        assert exit_result is not None
        # 3. Verify that a change occurred, as the volume was previously detached.
        assert exit_result["changed"] is True
        # 4. Verify that the returned resource (the volume) now shows it is attached to an instance.
        assert "resource" in exit_result

    def test_detach_volume(self, auth_params):
        """
        Verify that a volume can be successfully detached from an instance.
        """
        # --- ARRANGE ---
        # Define the user's desired state for attaching the volume.
        user_params = {
            "state": "absent",
            "volume": self.TEST_DATA["volume"],
            "instance": self.TEST_DATA["instance"],
            "project": self.TEST_DATA["project"],  # Context for resolving resources
            "tenant": self.TEST_DATA["tenant"],
            "device": "/dev/vdf",  # Optional parameter for the link operation
            **auth_params,
        }

        # --- ACT ---
        # Use the generic harness to run the module with the defined parameters.
        exit_result, fail_result = run_module_harness(
            volume_attachment_module, user_params
        )

        # --- ASSERT ---
        # 1. Ensure the module did not fail unexpectedly.
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        # 2. Ensure the module exited successfully.
        assert exit_result is not None
        # 3. Verify that a change occurred, as the volume was previously detached.
        assert exit_result["changed"] is True
        # 4. Verify that the returned resource (the volume) now shows it is attached to an instance.
        assert "resource" in exit_result
