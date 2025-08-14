import json
from urllib.parse import urlencode
import uuid

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
    ):
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

        # 2. Build the base URL
        url = f"{self.module.params['api_url']}{path}"

        # 3. Safely encode and append query parameters
        if query_params:
            url += "?" + urlencode(query_params)

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

        # 4. Handle failed requests with detailed error messages
        if info["status"] not in [200, 201, 202, 204]:
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

            msg = f"Request to {url} failed. Status: {info['status']}. Message: {info['msg']}. {error_details}"
            self.module.fail_json(msg=msg)

        # 5. Handle successful responses
        # Handle 204 No Content - success with no body
        if info["status"] == 204 or not body_content:
            return None

        # Try to parse the successful response as JSON
        try:
            return json.loads(body_content)
        except json.JSONDecodeError:
            # The server returned a 2xx status but the body was not valid JSON
            self.module.fail_json(
                msg=f"API returned a success status ({info['status']}) but the response was not valid JSON.",
                response_body=body_content.decode(errors="ignore"),
            )

    def _is_uuid(self, val):
        """
        Checks if a value is a UUID.
        """
        try:
            uuid.UUID(str(val))
            return True
        except (ValueError, TypeError, AttributeError):
            return False

    def _resolve_to_url(self, path, value, error_message):
        """
        Resolves a resource name or UUID to its API URL.
        """
        if self._is_uuid(value):
            # This assumes that the path for a single resource is the list path + uuid
            return f"{self.module.params['api_url']}{path}{value}/"

        response = self._send_request("GET", path, query_params={"name": value})
        if not response:
            self.module.fail_json(msg=error_message)
        return response[0]["url"]
