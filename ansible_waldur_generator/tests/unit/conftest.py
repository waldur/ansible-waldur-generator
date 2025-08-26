from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def mock_ansible_module():
    """
    A pytest fixture that provides a mocked AnsibleModule instance for each test.
    This prevents tests from interfering with each other and from exiting the test runner.
    """
    # We patch 'AnsibleModule' in the runner's namespace to avoid import issues.
    with patch(
        "ansible_waldur_generator.interfaces.runner.AnsibleModule"
    ) as mock_class:
        mock_module = mock_class.return_value
        mock_module.params = {}  # Start with empty params for each test
        mock_module.check_mode = False

        # Mock the exit methods to prevent sys.exit and to capture their arguments
        mock_module.exit_json = MagicMock()
        mock_module.fail_json = MagicMock()
        mock_module.warn = MagicMock()

        yield mock_module
