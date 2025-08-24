import json
import time
import uuid
from urllib.parse import urlencode

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.urls import fetch_url


class BaseRunner:
    """
    Abstract base class for all module runners.
    It handles common initialization tasks, such as setting up the API client
    and preparing the execution environment.
    """

    def __init__(self, module: AnsibleModule, context: dict):
        """
        Initializes the runner.

        Args:
            module: The AnsibleModule instance.
            context: A dictionary containing configuration and data for the runner.
        """
        self.module = module
        self.context = context
        self.has_changed = False
        self.resource = None

    def run(self):
        """
        The main execution method for the runner.
        This method should be implemented by all subclasses.
        """
        raise NotImplementedError

    def _send_request(
        self, method, path, data=None, query_params=None, path_params=None
    ) -> tuple[any, int]:
        """
        A wrapper around fetch_url to handle API requests robustly.
        """
        # 1. Handle path parameters safely
        if path_params:
            try:
                path = path.format(**path_params)
            except KeyError as e:
                self.module.fail_json(
                    msg=f"Missing required path parameter in API call: {e}"
                )
                return

        # 2. Build the final URL, handling both relative paths and absolute URLs.
        # If the path is already a full URL, use it directly. Otherwise, prepend the api_url.
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = f"{self.module.params['api_url'].rstrip('/')}/{path.lstrip('/')}"

        # 3. Safely encode and append query parameters
        if query_params:
            # Convert list values to repeated parameters
            encoded_params = []
            for key, value in query_params.items():
                if isinstance(value, list):
                    for v in value:
                        encoded_params.append((key, v))
                else:
                    encoded_params.append((key, value))
            url += "?" + urlencode(encoded_params)

        # Prepare data for the request body
        # Ansible's fetch_url handles dict->json conversion if headers are correct,
        # but being explicit is safer.
        if data and not isinstance(data, str):
            data = self.module.jsonify(data)

        # Make the request
        response, info = fetch_url(
            self.module,
            url,
            headers={
                "Authorization": f"token {self.module.params['access_token']}",
                "Content-Type": "application/json",
            },
            method=method,
            data=data,
            timeout=30,  # Best practice: always add a timeout
        )

        # Read the response body, if it exists
        body_content = None
        if response:
            body_content = response.read()

        status_code = info["status"]

        # 4. Handle failed requests with detailed error messages
        if status_code not in [200, 201, 202, 204]:
            error_details = ""
            if body_content:
                try:
                    # Try to parse the error body for more details
                    error_json = json.loads(body_content)
                    error_details = f"API Response: {json.dumps(error_json, indent=2)}"
                except json.JSONDecodeError:
                    # The error body was not JSON
                    error_details = (
                        f"API Response (raw): {body_content.decode(errors='ignore')}"
                    )

            msg = f"Request to {url} failed. Status: {status_code}. Message: {info['msg']}. {error_details}. Payload: {data}"
            self.module.fail_json(msg=msg)
            return (error_details, status_code)

        # 5. Handle successful responses
        # Handle 204 No Content - success with no body
        if not body_content:
            # For GET requests, an empty response body should be an empty list,
            # not None, to prevent TypeErrors in callers. For other methods,
            # None is appropriate for "No Content" responses.
            # For GET, return empty list; for others, return None.
            body = [] if method == "GET" else None
            return body, status_code

        # Try to parse the successful response as JSON
        try:
            return json.loads(body_content), status_code
        except json.JSONDecodeError:
            # The server returned a 2xx status but the body was not valid JSON
            self.module.fail_json(
                msg=f"API returned a success status ({info['status']}) but the response was not valid JSON.",
                response_body=body_content.decode(errors="ignore"),
            )
            return

    def _is_uuid(self, val):
        """
        Checks if a value is a UUID.
        """
        try:
            uuid.UUID(str(val))
            return True
        except (ValueError, TypeError, AttributeError):
            return False

    def _wait_for_resource_state(self, resource_uuid: str):
        """
        Polls a resource by its UUID until it reaches a stable state (OK or Erred).
        This is a generic utility for actions that trigger asynchronous background jobs.
        """
        wait_config = self.context.get("wait_config", {})
        if not wait_config:
            self.module.fail_json(
                msg="Runner Error: _wait_for_resource_state called but 'wait_config' is not defined in the runner context."
            )
            return

        # The path to the resource's detail view, used for polling.
        # We'll configure plugins to ensure this key is in the context.
        polling_path = self.context.get("resource_detail_path")
        if not polling_path:
            self.module.fail_json(
                msg="Runner Error: 'resource_detail_path' is required in runner context for waiting."
            )
            return

        ok_states = wait_config.get("ok_states", ["OK"])
        erred_states = wait_config.get("erred_states", ["Erred"])
        state_field = wait_config.get("state_field", "state")

        timeout = self.module.params.get("timeout", 600)
        interval = self.module.params.get("interval", 20)
        start_time = time.time()

        while time.time() - start_time < timeout:
            resource_state, status_code = self._send_request(
                "GET", polling_path, path_params={"uuid": resource_uuid}
            )

            if status_code == 404:
                # This can happen in a terminate/delete workflow where the resource disappears
                # before we can confirm its final state. We can consider this a success.
                self.resource = None
                return

            if resource_state:
                current_state = resource_state.get(state_field)
                if current_state in ok_states:
                    self.resource = resource_state  # Update runner's resource state
                    return
                if current_state in erred_states:
                    self.module.fail_json(
                        msg=f"Resource action resulted in an error state: '{current_state}'.",
                        resource=resource_state,
                    )
                    return  # Unreachable

            time.sleep(interval)

        self.module.fail_json(
            msg=f"Timeout waiting for resource {resource_uuid} to become stable."
        )
