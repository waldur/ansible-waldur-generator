import pytest

# Import the module under test with a clear alias
from ansible_collections.waldur.openstack.plugins.modules import (
    vpc_action as vpc_action_module,
)
from ansible_waldur_generator.tests.e2e.conftest import run_module_harness


@pytest.mark.vcr
class TestVpcActionModule:
    """
    Groups all end-to-end tests for the 'vpc_action' module, which is generated
    by the 'actions' plugin to perform operations on OpenStack tenants.
    """

    # Define consistent test data for identifying the target resource.
    TEST_DATA = {
        "vpc_name": "waldur-dev-farm",
        "project": "Self-Service dev infrastructure",
    }

    def test_pull_vpc(self, auth_params):
        """
        Verify that the 'pull' action can be successfully executed on an
        existing OpenStack tenant (VPC).
        """
        # --- ARRANGE ---
        # Define the user's desired action in the playbook.
        user_params = {
            # The 'action' parameter specifies which operation to perform.
            "action": "pull",
            # Parameters to identify the target resource.
            "name": self.TEST_DATA["vpc_name"],
            "project": self.TEST_DATA["project"],
            # Standard authentication and waiter parameters.
            "wait": False,  # Set to False for faster tests if the action is quick.
            **auth_params,
        }

        # --- ACT ---
        # Use the generic harness to run the module with the defined parameters.
        exit_result, fail_result = run_module_harness(vpc_action_module, user_params)

        # --- ASSERT ---
        # 1. Ensure the module did not fail unexpectedly.
        assert fail_result is None, f"Module failed unexpectedly with: {fail_result}"

        # 2. Ensure the module exited successfully.
        assert exit_result is not None

        # 3. Verify that a change occurred. Modules using the 'actions' plugin
        #    should always report a change on successful execution.
        assert exit_result["changed"] is True

        # 4. Verify that the command executed was for the 'pull' action.
        assert "commands" in exit_result
        assert len(exit_result["commands"]) == 1
        command = exit_result["commands"][0]
        assert command["method"] == "POST"
        assert "pull" in command["url"]
        assert "Execute action 'pull'" in command["description"]

        # 5. Verify that the module returned the state of the resource after the action.
        assert "resource" in exit_result
        assert exit_result["resource"]["name"] == self.TEST_DATA["vpc_name"]
