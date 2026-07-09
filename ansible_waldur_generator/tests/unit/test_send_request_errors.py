"""
Tests for BaseRunner.send_request error handling, focusing on the distinction
between a genuine empty result set and a failed network request.

The critical case guarded here: Ansible's `fetch_url` reports connection-level
failures (DNS failure, connection refused, timeout, dropped VPN) by returning
`response=None` and a synthetic status of -1. Such failures must fail the task,
not be silently reported as an empty list of resources.
"""

from unittest.mock import MagicMock, patch

import pytest

from ansible_waldur_generator.interfaces.runner import BaseRunner


class ConcreteRunner(BaseRunner):
    """Minimal concrete runner so BaseRunner can be instantiated in tests."""

    def plan_creation(self):
        return []

    def plan_update(self):
        return []

    def plan_deletion(self):
        return []


@pytest.fixture
def mock_ansible_module():
    module = MagicMock()
    module.params = {
        "access_token": "dummy-token",
        "api_url": "https://waldur.example.com/",
    }
    # Make fail_json raise so the test can assert that execution stops there,
    # mirroring the real AnsibleModule.fail_json (which calls sys.exit).
    module.fail_json.side_effect = Exception("FailJsonCalled")
    module.jsonify = MagicMock()
    return module


def _make_runner(module):
    return ConcreteRunner(module, context={})


@patch("ansible_waldur_generator.interfaces.runner.fetch_url")
def test_connection_failure_fails_task(mock_fetch_url, mock_ansible_module):
    """A connection-level failure (status -1, no body) must fail the task."""
    # This is exactly what fetch_url returns on a dropped connection/timeout.
    mock_fetch_url.return_value = (
        None,
        {"status": -1, "msg": "Connection failure: timed out"},
    )

    runner = _make_runner(mock_ansible_module)

    with pytest.raises(Exception, match="FailJsonCalled"):
        runner.send_request("GET", "/api/openstack-instances/")

    mock_ansible_module.fail_json.assert_called_once()
    msg = mock_ansible_module.fail_json.call_args.kwargs["msg"]
    assert "no response received" in msg
    assert "Connection failure: timed out" in msg


@patch("ansible_waldur_generator.interfaces.runner.fetch_url")
def test_genuine_empty_list_is_not_an_error(mock_fetch_url, mock_ansible_module):
    """A real 200 response with an empty JSON list must NOT fail the task."""
    empty_response = MagicMock()
    empty_response.read.return_value = b"[]"
    mock_fetch_url.return_value = (empty_response, {"status": 200})

    runner = _make_runner(mock_ansible_module)
    data, status = runner.send_request("GET", "/api/openstack-instances/")

    assert data == []
    assert status == 200
    mock_ansible_module.fail_json.assert_not_called()


@patch("ansible_waldur_generator.interfaces.runner.fetch_url")
def test_http_error_still_fails_task(mock_fetch_url, mock_ansible_module):
    """An HTTP-level error (>= 400) must keep failing the task as before."""
    mock_fetch_url.return_value = (
        None,
        {"status": 403, "msg": "Forbidden", "body": b'{"detail": "nope"}'},
    )

    runner = _make_runner(mock_ansible_module)

    with pytest.raises(Exception, match="FailJsonCalled"):
        runner.send_request("GET", "/api/openstack-instances/")

    mock_ansible_module.fail_json.assert_called_once()
