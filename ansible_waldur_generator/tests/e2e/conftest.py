import os
import json

from unittest.mock import patch, MagicMock

import pytest


def run_module_harness(ansible_module, module_params):
    """
    A generic test harness for running any generated Ansible module.

    Args:
        ansible_module: The imported module object (e.g., volume_module).
        module_params (dict): A dictionary of parameters to simulate user input.

    Returns:
        A tuple containing the results from exit_json and fail_json.
    """
    results = {"exit_json": None, "fail_json": None}

    # Real Ansible fills unsupplied parameters from argument_spec defaults before
    # the module sees them. Handing over the raw dict instead left every
    # defaulted field as None here, so a module could pass its tests while
    # behaving differently under Ansible -- and a missing default in
    # argument_spec, which breaks a real run, was invisible.
    effective_params = {
        name: spec["default"]
        for name, spec in getattr(ansible_module, "ARGUMENT_SPEC", {}).items()
        if "default" in spec
    }
    effective_params.update(module_params)

    # Patch AnsibleModule within the specific module's namespace
    with patch.object(ansible_module, "AnsibleModule") as mock_ansible_module_class:
        mock_module_instance = MagicMock()
        mock_module_instance.params = effective_params
        mock_module_instance.check_mode = False
        mock_module_instance.exit_json.side_effect = lambda **kwargs: results.update(
            exit_json=kwargs
        )
        mock_module_instance.fail_json.side_effect = lambda **kwargs: results.update(
            fail_json=kwargs
        )
        # Add jsonify, as it's called by the runner to prepare request bodies
        mock_module_instance.jsonify = json.dumps

        mock_ansible_module_class.return_value = mock_module_instance

        # Call the main function of the provided module
        ansible_module.main()

    return results["exit_json"], results["fail_json"]


@pytest.fixture
def auth_params():
    """Provides a dictionary with standard authentication and API URL parameters."""
    return {
        "access_token": os.environ.get("WALDUR_ACCESS_TOKEN", "dummy-token-for-replay"),
        "api_url": os.environ.get("WALDUR_API_URL", "http://127.0.0.1:8000/"),
    }


@pytest.fixture(scope="module")
def vcr_config():
    return {
        # Replace the Authorization request header with "DUMMY" in cassettes
        "filter_headers": [("authorization", "DUMMY")],
    }
