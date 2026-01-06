import pytest
from unittest.mock import MagicMock
from ansible_waldur_generator.plugins.order.runner import OrderRunner


@pytest.fixture
def mock_runner_setup():
    module = MagicMock()
    module.params = {}
    module.fail_json = MagicMock()

    context = {
        "marketplace_resource_check_url": "/api/marketplace-resources/",
        "name_query_param": "name_exact",
        "resource_type": "TestResource",
        "resolvers": {},  # needed for ParameterResolver init
    }

    runner = OrderRunner(module, context)
    runner.send_request = MagicMock()
    runner.resolver = MagicMock()
    return runner, module


def test_check_existence_uses_marketplace_lookup_when_offering_present(
    mock_runner_setup,
):
    runner, module = mock_runner_setup
    module.params = {"offering": "offering-name", "name": "resource-name"}

    # Mock resolving offering
    runner.resolver.resolve.return_value = "offering-uuid"

    # Mock marketplace response
    marketplace_resource = {
        "uuid": "mr-uuid",
        "scope": "/api/plugin-resources/res-uuid/",
    }
    plugin_resource = {"uuid": "res-uuid", "name": "resource-name"}

    # send_request side effects:
    # 1. Marketplace lookup -> [marketplace_resource]
    # 2. Scope lookup -> plugin_resource
    runner.send_request.side_effect = [
        ([marketplace_resource], None),
        (plugin_resource, None),
    ]

    # Act
    runner.check_existence()

    # Assert
    # 1. Verify offering was resolved
    runner.resolver.resolve.assert_called_with("offering", "offering-name")

    # 2. Verify marketplace lookup
    runner.send_request.assert_any_call(
        "GET",
        "/api/marketplace-resources/",
        query_params={
            "offering_uuid": "offering-uuid",
            "name_exact": "resource-name",
            "state": ["OK", "Erred", "Creating", "Updating", "Terminating"],
        },
    )

    # 3. Verify scope lookup
    runner.send_request.assert_any_call("GET", "/api/plugin-resources/res-uuid/")

    # 4. Verify resource is set and has marketplace UUID attached
    assert runner.resource == plugin_resource
    assert runner.resource["marketplace_resource_uuid"] == "mr-uuid"


def test_check_existence_handles_no_offering(mock_runner_setup):
    runner, module = mock_runner_setup
    module.params = {"name": "resource-name"}  # No offering

    # Mock super().check_existence behavior (which uses check_url)
    runner.context["check_url"] = "/api/plugin-resources/"
    plugin_resource = {"uuid": "res-uuid"}
    runner.send_request.side_effect = [([plugin_resource], None)]

    # Act
    runner.check_existence()

    # Assert
    # Should NOT call marketplace lookup
    # Should call standard lookup
    runner.send_request.assert_called_with(
        "GET", "/api/plugin-resources/", query_params={"name_exact": "resource-name"}
    )
    assert runner.resource == plugin_resource


def test_check_existence_handles_marketplace_resource_not_found(mock_runner_setup):
    runner, module = mock_runner_setup
    module.params = {"offering": "offering-name", "name": "resource-name"}
    runner.resolver.resolve.return_value = "offering-uuid"

    # Marketplace lookup returns empty
    runner.send_request.return_value = ([], None)

    # Act
    runner.check_existence()

    # Assert
    assert runner.resource is None


def test_check_existence_handles_multiple_marketplace_resources(mock_runner_setup):
    runner, module = mock_runner_setup
    module.params = {"offering": "offering-name", "name": "resource-name"}
    runner.resolver.resolve.return_value = "offering-uuid"

    # Marketplace lookup returns multiple ACTIVE resources with valid scopes
    runner.send_request.return_value = (
        [
            {"scope": "http://api.com/resource/1", "state": "OK"},
            {"scope": "http://api.com/resource/2", "state": "OK"},
        ],
        None,
    )

    # Act
    runner.check_existence()

    # Assert
    module.fail_json.assert_called()
    assert "Multiple active resources found" in module.fail_json.call_args[1]["msg"]


def test_check_existence_handles_missing_scope(mock_runner_setup):
    runner, module = mock_runner_setup
    module.params = {"offering": "offering-name", "name": "resource-name"}
    runner.resolver.resolve.return_value = "offering-uuid"

    # Marketplace resource has no scope
    marketplace_resource = {"uuid": "mr-uuid", "scope": None}
    runner.send_request.return_value = ([marketplace_resource], None)

    # Act
    runner.check_existence()

    # Assert
    assert runner.resource is None


def test_check_existence_ignores_resources_in_other_offerings(mock_runner_setup):
    """
    Scenario: User wants to create 'test-vpc' in 'Datacenter 2' (Offering B).
    'test-vpc' ALREADY exists in 'Datacenter 1' (Offering A).

    We must ensure that check_existence uses the offering_uuid of Offering B
    so that it does NOT find the resource from Offering A.
    """
    runner, module = mock_runner_setup
    module.params = {"offering": "Datacenter 2", "name": "test-vpc"}

    # 1. Resolve Offering B
    runner.resolver.resolve.return_value = "offering-b-uuid"

    # 2. Mock Marketplace behavior
    # The runner asks for: offering_uuid="offering-b-uuid", name="test-vpc"
    # We should return [] because it doesn't exist in B yet.
    runner.send_request.return_value = ([], None)

    # Act
    runner.check_existence()

    # Assert
    # Verify we resolved the correct offering
    runner.resolver.resolve.assert_called_with("offering", "Datacenter 2")

    # Verify the API call explicitly filtered by offering-b-uuid
    runner.send_request.assert_called_with(
        "GET",
        "/api/marketplace-resources/",
        query_params={
            "offering_uuid": "offering-b-uuid",
            "name_exact": "test-vpc",
            "state": ["OK", "Erred", "Creating", "Updating", "Terminating"],
        },
    )

    # Verify result is None (forcing creation)
    assert runner.resource is None
