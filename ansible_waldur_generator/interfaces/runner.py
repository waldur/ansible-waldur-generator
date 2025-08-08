from typing import Any
import uuid
from ansible.module_utils.basic import AnsibleModule
from waldur_api_client.client import AuthenticatedClient


class BaseRunner:
    """Abstract base class for all module runners, containing shared utilities."""

    def __init__(self, module: AnsibleModule, context: dict):
        self.module = module
        self.context = context
        self.client = AuthenticatedClient(
            base_url=module.params["api_url"], token=module.params["access_token"]
        )
        self.has_changed = False

    def run(self):
        """Each subclass must implement its own execution logic."""
        raise NotImplementedError

    def _is_uuid(self, val: Any) -> bool:
        """Checks if a value can be interpreted as a valid UUID."""
        try:
            uuid.UUID(str(val))
            return True
        except (ValueError, TypeError, AttributeError):
            return False

    def _resolve_to_url(self, list_func, retrieve_func, value, error_message):
        """
        Resolves a resource name or UUID to its API URL.
        Uses the more efficient 'retrieve' function for UUIDs and 'list' for names.
        """
        if not value:
            return None
        if str(value).startswith(("http://", "https://")):
            return value
        try:
            if self._is_uuid(value):
                resource = retrieve_func.sync(client=self.client, uuid=value)
                resources = [resource] if resource else []
            else:
                resources = list_func.sync(client=self.client, name_exact=value)

            if not resources:
                self.module.fail_json(msg=error_message.format(value=value))
            if len(resources) > 1:
                self.module.fail_json(
                    msg=f"Multiple resources found for '{value}'. Please use UUID for uniqueness."
                )

            return resources[0].url
        except Exception as e:
            self.module.fail_json(msg=f"Failed to resolve '{value}': {str(e)}")
