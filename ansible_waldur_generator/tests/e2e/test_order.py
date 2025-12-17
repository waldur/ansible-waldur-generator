import pytest
from ansible_collections.waldur.marketplace.plugins.modules import (
    order as order_module,
)
from ansible_waldur_generator.tests.e2e.conftest import run_module_harness


@pytest.mark.vcr
class TestOrderModule:
    """End-to-end tests for the marketplace order module using VCR."""

    TEST_DATA = {
        "project": "d75",
        "offering": "fcf6fac7221f49c8b6a33011f5bfc1b6",
        "resource_name": "E2E Test Order Resource",
    }

    def test_create_order_basic(self, auth_params):
        """Test creating a basic marketplace order for a new resource."""
        user_params = {
            "state": "present",
            "name": self.TEST_DATA["resource_name"],
            "project": self.TEST_DATA["project"],
            "offering": self.TEST_DATA["offering"],
            "limits": {},
            "attributes": {"permissions": "775", "storage_data_type": "Store"},
            "accepting_terms_of_service": True,
            "plan": "http://127.0.0.1:8000/api/marketplace-public-offerings/fcf6fac7221f49c8b6a33011f5bfc1b6/plans/b2fdf9491a1f4d09b2ecba79a479a949/",
            "wait": False,
            **auth_params,
        }

        exit_result, fail_result = run_module_harness(order_module, user_params)

        # ASSERT
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"
        assert exit_result is not None
        assert exit_result["changed"] is True
        # Verify that a marketplace order was created
        assert len(exit_result["commands"]) > 0
        command = exit_result["commands"][0]
        assert command["method"] == "POST"
        assert "/api/marketplace-orders/" in command["url"]
        # Verify core fields are present
        assert "project" in command["body"]
        assert "offering" in command["body"]
        assert "attributes" in command["body"]
