from abc import abstractmethod
import json
import time
import uuid
from urllib.parse import urlencode

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.urls import fetch_url

from .command import Command


class BaseRunner:
    """
    Abstract base class for all module runners.
    It handles common initialization, API requests, and orchestrates a
    two-phase "plan and execute" workflow using the Command pattern.
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
        self.plan = []

    @abstractmethod
    def plan_creation(self) -> list:
        """
        Abstract method for planning the creation of a resource.
        Subclasses must implement this to return a list of CreateCommands or
        handle special creation workflows.
        """
        pass

    @abstractmethod
    def plan_update(self) -> list:
        """
        Abstract method for planning the update of an existing resource.
        Subclasses must implement this to perform any necessary setup (like
        cache priming) and return a list of Update/ActionCommands.
        """
        pass

    @abstractmethod
    def plan_deletion(self) -> list:
        """
        Abstract method for planning the deletion of an existing resource.
        Subclasses must implement this to return a list of DeleteCommands.
        """
        pass

    def run(self):
        """
        The universal, final `run` method for all runners.

        This orchestrator implements the complete, shared logic for module
        execution. It determines the current state of the resource and then
        delegates the "planning" of what to do to the specialized abstract
        methods (`plan_creation`, `plan_update`, `plan_deletion`).

        This completely removes the need for subclasses to implement their own
        `run` method, ensuring a consistent, robust workflow across all module types.
        """
        # Step 1: Determine the initial state of the resource. This is crucial
        # for all subsequent planning.
        self.check_existence()

        # Step 2: Delegate planning to the appropriate abstract method based on
        # the desired state and the resource's current existence.
        state = self.module.params["state"]
        if self.resource:
            if state == "present":
                self.plan = self.plan_update()
            elif state == "absent":
                self.plan = self.plan_deletion()
        elif state == "present":
            self.plan = self.plan_creation()

        # Step 3: Handle Check Mode.
        if self.module.check_mode:
            self.handle_check_mode(self.plan)
            return

        # Step 4: Execute the generated plan.
        self.execute_change_plan(self.plan)

        # Step 5: Exit with the final state and a diff generated from the plan.
        self.exit(plan=self.plan)

    def exit(self, plan: list | None = None, commands: list | None = None):
        """
        Formats the final response for Ansible and exits the module.
        """
        if commands is None:
            commands = [cmd.serialize_request() for cmd in plan] if plan else []

        self.module.exit_json(
            changed=self.has_changed,
            resource=self.resource,
            commands=commands,
        )

    def execute_change_plan(self, plan: list):
        """
        Executes a list of Command objects, making the actual API calls and
        triggering asynchronous waiters if required.
        """
        if not plan:
            return

        self.has_changed = True

        for command in plan:
            result = command.execute()

            # Update runner's internal state based on the type of command executed.
            if command.command_type == "create":
                self.resource = result
            elif command.command_type == "order":
                # For an order, the result is the order object itself.
                # The final resource will be fetched by the waiter.
                self.order = result
                self.resource = None  # It doesn't exist yet.
            elif command.command_type == "delete":
                self.resource = None
            elif command.command_type == "update" and self.resource and result:
                self.resource.update(result)
            # For 'action' commands, the resource state is typically updated by the waiter.

            # --- Generic Waiting Logic ---
            if command.wait_config and self.module.params.get("wait", True):
                # Determine the UUID to poll based on the command's context.
                uuid_source_config = command.wait_config.get("uuid_source", {})
                uuid_source_location = uuid_source_config.get("location")
                uuid_key = uuid_source_config.get("key")
                uuid_to_poll = None

                if uuid_source_location == "result_body" and result:
                    uuid_to_poll = result.get(uuid_key)
                elif uuid_source_location == "resource" and self.resource:
                    uuid_to_poll = self.resource.get(uuid_key)

                if uuid_to_poll:
                    self._wait_for_completion(
                        polling_path=command.wait_config["polling_path"],
                        resource_uuid=uuid_to_poll,
                        wait_config=command.wait_config,
                    )
                else:
                    self.module.fail_json(
                        msg=f"Could not determine UUID to poll for async action. Source config: {uuid_source_config}"
                    )

    def handle_check_mode(self, plan: list):
        """
        Generates a predictive diff from a change plan and exits.
        """
        if plan:
            self.has_changed = True
        # The specialized runner's exit method will handle the diff.
        self.exit(commands=[cmd.serialize_request() for cmd in plan])

    def send_request(
        self, method, path, data=None, query_params=None, path_params=None
    ) -> tuple[any, int]:
        """
        A robust, centralized wrapper around Ansible's `fetch_url` utility to
        handle all API requests to the Waldur backend.

        This method is the single point of entry for all network communication
        in any generated module. It is responsible for:
        1.  **URL Construction:** Correctly building the full request URL from the
            API base URL, the relative path, and any query or path parameters.
            It also handles pre-signed absolute URLs.
        2.  **Authentication:** Injecting the required 'Authorization' header
            with the user-provided access token into every request.
        3.  **Payload Handling:** Serializing Python dictionaries into JSON for
            request bodies.
        4.  **Robust Error Handling:** Intercepting non-successful HTTP status
            codes (>= 400), parsing the detailed error message from the API
            response body, and failing the Ansible module with a clear,
            structured, and user-friendly error message.
        5.  **Success Response Parsing:** Parsing the JSON response body for
            successful requests and handling special cases like '204 No Content'.

        By centralizing this logic, we ensure consistent behavior, authentication,
        and error reporting across all generated Ansible modules.

        Args:
            method (str): The HTTP method (e.g., 'GET', 'POST', 'PATCH').
            path (str): The relative API endpoint path (e.g., '/api/projects/') or a full pre-signed URL.
            data (dict, optional): The request body payload. Defaults to None.
            query_params (dict, optional): A dictionary of query parameters. Defaults to None.
            path_params (dict, optional): Parameters to format into the path for nested endpoints. Defaults to None.

        Returns:
            A tuple containing the parsed JSON response (or None for '204 No Content')
            and the integer HTTP status code.
        """
        # --- Step 1: URL and Path Parameter Assembly ---

        # If path parameters are provided (e.g., for nested endpoints like '/api/networks/{uuid}/subnets/'),
        # format them into the path string. This is a critical first step.
        if path_params:
            try:
                path = path.format(**path_params)
            except KeyError as e:
                # Fail early if a required placeholder is missing from the provided parameters.
                self.module.fail_json(
                    msg=f"Internal configuration error: Missing required path parameter in API call: {e}"
                )
                return None, 0  # Unreachable

        # Determine the final URL. If the path is already a full URL (e.g., from a previous
        # API response), use it directly. Otherwise, construct it by combining the
        # base `api_url` with the relative endpoint path.
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            api_url_base = self.module.params["api_url"].rstrip("/")
            path_relative = path.lstrip("/")
            url = f"{api_url_base}/{path_relative}"

        # Safely encode and append query parameters to the URL. This handles special
        # characters and correctly formats list values as repeated parameters (e.g., ?key=v1&key=v2).
        if query_params:
            encoded_params = []
            for key, value in query_params.items():
                if isinstance(value, list):
                    for v_item in value:
                        encoded_params.append((key, v_item))
                else:
                    encoded_params.append((key, value))
            url += "?" + urlencode(encoded_params)

        # --- Step 2: Prepare Request Body and Headers ---

        # If a data payload is provided, serialize it to a JSON string. Ansible's `fetch_url`
        # requires the `data` argument to be a byte string for POST/PUT/PATCH requests.
        if data and not isinstance(data, str):
            data = self.module.jsonify(data)

        # Define the standard headers for all API requests.
        headers = {
            "Authorization": f"token {self.module.params['access_token']}",
            "Content-Type": "application/json",
        }

        # --- Step 3: Execute the API Request ---

        # Call Ansible's built-in `fetch_url` utility to perform the HTTP request.
        # This is the only place in the codebase that makes a network call.
        response, info = fetch_url(
            self.module,
            url,
            data=data,
            headers=headers,
            method=method,
            timeout=30,  # A sensible default timeout to prevent hung tasks.
        )

        # --- Step 4: Process the Response ---

        status_code = info["status"]

        # Handle non-successful status codes (e.g., 400, 403, 404, 500).
        if status_code >= 400:
            # As per the `fetch_url` contract, the error response body is located in `info['body']`.
            error_body = info.get("body", b"")
            error_json = None
            error_details_str = "No detailed error message from API."

            if error_body:
                try:
                    # Attempt to parse the error body as JSON, as this is the standard
                    # format for detailed errors from the Waldur API.
                    error_json = json.loads(error_body)
                    # Create a pretty-printed string version for the main error message.
                    error_details_str = (
                        f"API Response: {json.dumps(error_json, indent=2)}"
                    )
                except json.JSONDecodeError:
                    # If the body is not JSON, fall back to a raw string representation.
                    error_details_str = (
                        f"API Response (raw): {error_body.decode(errors='ignore')}"
                    )

            # Construct a comprehensive, user-friendly error message.
            msg = (
                f"Request to {url} failed. Status: {status_code}. "
                f"Message: {info['msg']}. {error_details_str}. Payload: {data}"
            )

            # Fail the Ansible module, providing both the comprehensive message and the
            # structured JSON error for easier parsing and debugging in playbooks.
            self.module.fail_json(msg=msg, api_error=error_json)
            return error_json, status_code  # Unreachable

        # Handle successful responses.
        body_content = None
        if response:
            # For successful requests, the response body is a file-like object
            # that must be read.
            body_content = response.read()

        # Handle '204 No Content' - a successful request with an intentionally empty body.
        if status_code == 204 or not body_content:
            # For GET requests, an empty response should be an empty list to prevent
            # TypeErrors in the calling code. For other methods (POST, PATCH),
            # None is the correct representation of "No Content".
            body = [] if method == "GET" else None
            return body, status_code

        # Attempt to parse the successful response body as JSON.
        try:
            return json.loads(body_content), status_code
        except json.JSONDecodeError:
            # This is an exceptional case: the API returned a success status (2xx)
            # but the response body was not valid JSON, indicating a potential API bug
            # or proxy issue.
            self.module.fail_json(
                msg=f"API returned a success status ({status_code}) but the response was not valid JSON.",
                response_body=body_content.decode(errors="ignore"),
            )
            return None, status_code  # Unreachable

    def _is_uuid(self, val):
        """
        Checks if a value is a UUID.
        """
        try:
            uuid.UUID(str(val))
            return True
        except (ValueError, TypeError, AttributeError):
            return False

    def _wait_for_completion(
        self, polling_path: str, resource_uuid: str, wait_config: dict
    ):
        """
        A generic poller for an asynchronous task until it reaches a stable state.
        This is used for both marketplace orders and long-running resource actions.
        """
        ok_states = wait_config.get("ok_states", ["OK"])
        erred_states = wait_config.get("erred_states", ["Erred"])
        state_field = wait_config.get("state_field", "state")

        timeout = self.module.params.get("timeout", 600)
        interval = self.module.params.get("interval", 20)
        start_time = time.time()

        while time.time() - start_time < timeout:
            polled_data, status_code = self.send_request(
                "GET", polling_path, path_params={"uuid": resource_uuid}
            )

            if status_code == 404:
                # This can happen in a terminate/delete workflow where the resource disappears
                # before we can confirm its final state. We can consider this a success.
                self.resource = None
                return

            if polled_data:
                current_state = polled_data.get(state_field)
                if current_state in ok_states:
                    # For orders, we must re-fetch the *final provisioned resource*.
                    # For simple resource actions, the polled data *is* the final resource.
                    if wait_config.get("refetch_resource", False):
                        self.check_existence()
                    else:
                        self.resource = polled_data
                    return
                if current_state in erred_states:
                    self.module.fail_json(
                        msg=f"Task resulted in an error state: '{current_state}'.",
                        details=polled_data,
                    )
                    return  # Unreachable

            time.sleep(interval)

        self.module.fail_json(
            msg=f"Timeout waiting for task on resource {resource_uuid} to complete."
        )

    def _normalize_for_comparison(
        self, value: any, idempotency_keys: list[str], defaults_map: dict | None = None
    ) -> any:
        """
        Normalizes complex values (especially lists) into a canonical, order-insensitive,
        and comparable format. This method is the core of a robust idempotency check for
        complex parameters like lists of networks, security groups, or ports.

        The fundamental problem this solves is that a simple equality check (`!=`) is
        insufficient for lists, because:
        1.  `['a', 'b'] != ['b', 'a']`. The order matters, but for idempotency, it often shouldn't.
        2.  Lists can contain dictionaries, which are not "hashable" and cannot be put
            directly into a set for an order-insensitive comparison.

        This function operates in two primary modes to solve these problems:

        -   **Mode A (Complex Object Normalization):** When dealing with a list of dictionaries
            (e.g., port configurations) and guided by `idempotency_keys`, it transforms each
            dictionary into a canonical, sorted JSON string. These strings are then put into
            a set, creating a truly order-insensitive and comparable representation of the
            list's "identity."

        -   **Mode B (Simple Value Normalization):** When dealing with a list of simple,
            hashable values (like strings or numbers), it simply converts the list into a set.

        This dual-mode approach makes the idempotency check both powerful and flexible,
        correctly handling a wide variety of API schemas.

        Args:
            value:
                The value to normalize. This is typically the user-provided, resolved
                parameter value or the corresponding value from the existing resource.
            idempotency_keys:
                A list of dictionary keys that uniquely define the identity of an object
                within a list. This is a crucial piece of metadata inferred by the generator
                plugin from the API schema. For a port, this might be `['subnet', 'fixed_ips']`.

        Returns:
            A comparable, order-insensitive representation (typically a set),
            or the original value if normalization is not possible or not applicable.
        """
        defaults_map = defaults_map or {}

        # --- Guard Clause 1: Handle Non-List Values ---
        # This function is designed to normalize lists. If the input is anything else
        # (e.g., a string, integer, boolean, dict, or None), there is no concept of
        # "order" to normalize. We return the value as-is immediately.
        if not isinstance(value, list):
            return value

        # --- Guard Clause 2: Handle Empty Lists ---
        # An empty list `[]` should always have a consistent, canonical representation.
        # An empty set `set()` is the perfect choice, as it will correctly compare
        # as equal to any other normalized empty list.
        if not value:
            return set()

        # --- Main Logic: Determine Normalization Mode ---

        # Check if the list contains dictionaries and if we have the keys to normalize them.
        # We only check the first item for performance, assuming the list is homogeneous.
        is_complex_list = idempotency_keys and isinstance(value[0], dict)

        if is_complex_list:
            # --- MODE A: List of Complex Objects (e.g., Dictionaries) ---
            # We have the necessary `idempotency_keys` to guide the normalization of
            # otherwise un-comparable dictionaries.

            canonical_forms = set()
            for item in value:
                # Robustness check: If the list is mixed with non-dictionary items,
                # we cannot reliably normalize it. Abort and return the original list.
                # The subsequent idempotency check will safely fail (likely triggering
                # a harmless, redundant API call), but the module will not crash.
                if not isinstance(item, dict):
                    return value

                # Apply schema defaults if a schema is available.
                # We apply this to every item to handle both user input and resource state consistently.
                item_to_process = self._apply_defaults(item, defaults_map)

                # This is the core of the complex normalization. We create a new, temporary
                # dictionary containing ONLY the keys that define the object's identity.
                # This ensures we ignore transient or server-generated fields (like 'uuid'
                # or 'status') when comparing the user's desired state to the current state.
                keys_to_use = idempotency_keys or list(item_to_process.keys())
                filtered_item = {key: item_to_process.get(key) for key in keys_to_use}

                # We now convert this filtered dictionary into a canonical string. This string
                # is both hashable (so it can be added to a set) and deterministic.
                #   - `sort_keys=True`: Guarantees that `{'a': 1, 'b': 2}` and `{'b': 2, 'a': 1}`
                #     produce the exact same string. This is essential.
                #   - `separators=(",", ":")`: Creates the most compact JSON representation,
                #     removing any variations in whitespace.
                canonical_string = json.dumps(
                    filtered_item, sort_keys=True, separators=(",", ":")
                )
                canonical_forms.add(canonical_string)

            return canonical_forms
        else:
            # --- MODE B: List of Simple, Hashable Values (or Fallback) ---
            # This branch handles lists of strings, numbers, etc., where a direct
            # conversion to a set is the correct way to make it order-insensitive.

            try:
                # The most Pythonic and efficient way to check if all items are hashable
                # is to simply try to create a set from them.
                return set(value)
            except TypeError:
                # This block is a critical safety net. It will be reached if:
                #   a) The list contains unhashable types (like dictionaries).
                #   b) But we were NOT provided with `idempotency_keys` to handle them.
                # In this scenario, we cannot perform a reliable order-insensitive comparison.
                # The safest action is to return the original list. The `!=` check that
                # follows in the calling method will likely evaluate to True, but this is a
                # "safe failure" — it prevents a crash and at worst causes a redundant
                # API call, which the API endpoint should handle gracefully.
                return value

    def _build_simple_update_command(self) -> list:
        """
        Analyzes simple, direct attribute changes and returns a single UpdateCommand
        if and only if changes are detected.

        This method is the "planning" engine for basic idempotency. It compares
        each user-provided, updatable parameter against the current state of the
        resource. If any discrepancies are found, it bundles them into a single,
        atomic `UpdateCommand` that represents a PATCH request.

        Key Responsibilities:
        1.  **Iterate and Compare**: Loop through every field designated as updatable
            in the module's configuration (`update_fields`).
        2.  **Detect Changes**: For each field, perform a direct comparison between the
            user's desired value and the existing value on the resource.
        3.  **Build Structured Diff**: When a change is found, create a detailed dictionary
            containing the parameter name, the old value, and the new value. This
            structure is essential for providing clear, predictive diffs to the user.
        4.  **Aggregate Changes**: Collect all detected changes into a list.
        5.  **Command Generation**: If—and only if—the list of changes is non-empty,
            instantiate and return a single `UpdateCommand` containing all the
            changes. This ensures no command is generated (and thus no API call is made)
            if the resource is already in the desired state.

        Returns:
            A list containing a single `UpdateCommand` if changes are needed, or an
            empty list if the resource is already up-to-date.
        """
        # --- Step 1: Initial Setup and Guard Clauses ---

        # Retrieve the necessary configuration from the runner's context.
        # `update_path`: The URL template for the resource's update endpoint (e.g., "/api/instances/{uuid}/").
        # `update_fields`: A list of Ansible parameter names that are mutable (e.g., ["description", "name"]).
        update_path = self.context.get("update_path")
        update_fields = self.context.get("update_fields", [])

        # If there is no existing resource to update, no configured update endpoint,
        # or no fields are defined as updatable, then planning is impossible.
        # Return an empty list to signify that no action should be taken.
        if not (self.resource and update_path and update_fields):
            return []

        # --- Step 2: Detect Changes and Build the Diff List ---

        # This list will store a structured record of every detected change.
        # This is the data that will be used for both the API payload and the user-facing diff.
        changes = []

        # Iterate through each field that the module configuration has marked as updatable.
        for field in update_fields:
            # Get the value for this field from the user's Ansible playbook parameters.
            new_value = self.module.params.get(field)
            # Get the current value for this field from the existing resource data.
            old_value = self.resource.get(field)

            # The core idempotency check. A change is registered only if:
            #   a) The user has actually provided a value for it (`new_value is not None`).
            #      This is critical to prevent the module from trying to set a field to `null`
            #      just because the user omitted it from their playbook.
            #   b) The user-provided value is different from the value currently on the
            #      resource in Waldur. This handles all simple types (str, int, bool, etc.).
            if new_value is not None and new_value != old_value:
                # A change has been detected. Record it in our structured list.
                changes.append({"param": field, "old": old_value, "new": new_value})

        # --- Step 3: Generate the Command ---

        # If the `changes` list is not empty, it means at least one attribute needs to be updated.
        if changes:
            # Instantiate a single `UpdateCommand`. This object encapsulates everything
            # needed for both execution (the API path and payload) and for generating a diff.
            # The command is returned inside a list to maintain a consistent return type
            # with `_build_action_update_commands`.
            # The payload for the API call should only contain the *new* values.
            update_payload = {change["param"]: change["new"] for change in changes}
            return [
                Command(
                    self,
                    method="PATCH",
                    path=update_path,
                    command_type="update",
                    data=update_payload,
                    path_params={"uuid": self.resource["uuid"]},
                    description=f"Update attributes of {self.context['resource_type']}",
                )
            ]

        # If the `changes` list is empty, the resource is already in the desired state.
        # Return an empty list to signify that no `UpdateCommand` is necessary.
        return []

    def _build_action_update_commands(self, resolve_output_format="create") -> list:
        """
        Analyzes complex, action-based changes and returns a list of ActionCommands,
        one for each action that requires execution.

        This is the "planning" engine for advanced idempotency. It handles updates that
        are not simple PATCH requests but instead require POSTing to special action
        endpoints (e.g., updating security groups or network ports on a VM).

        Key Responsibilities:
        1.  **Iterate Actions**: Loop through every special update action defined in the
            module's configuration (`update_actions`).
        2.  **Resolve Desired State**: For each action, take the user's input (which can
            be a complex structure of names and UUIDs) and use the `ParameterResolver`
            to convert it into the precise data structure the API endpoint expects.
        3.  **Normalize for Comparison**: Convert both the newly resolved desired state
            and the current state from the resource into a canonical, order-insensitive
            format using the `_normalize_for_comparison` helper. This is the cornerstone
            of robustly comparing complex data like lists of objects.
        4.  **Detect Change**: Compare the two normalized representations. If they differ,
            a change is required.
        5.  **Command Generation**: For each detected change, instantiate a distinct
            `ActionCommand`. This command encapsulates the specific API path for the
            action, the resolved payload, and the old/new values for a precise diff.

        Returns:
            A list of `ActionCommand` objects, or an empty list if no actions need to be
            triggered.
        """
        # --- Step 1: Initial Setup and Guard Clauses ---

        # Retrieve the dictionary of configured actions from the runner's context.
        update_actions = self.context.get("update_actions", {})

        # If there's no existing resource to update or no actions are configured,
        # planning is impossible. Return an empty list.
        if not (self.resource and update_actions):
            return []

        # This list will hold all the `ActionCommand` objects we decide to create.
        commands = []

        # --- Step 2: Main Loop - Plan Each Action ---

        # Iterate through each action defined in the user's generator configuration.
        for _, action_info in update_actions.items():
            param_name = action_info["param"]
            param_value = self.module.params.get(param_name)

            # An action is only planned if the user has provided its corresponding parameter.
            # If the parameter is `None`, we skip this action entirely.
            if param_value is not None:
                # --- 2a. RESOLVE Desired State ---
                # Delegate to the ParameterResolver to convert the user's input (e.g., `['sg-web']`)
                # into the final, API-ready data structure (e.g., `[{'url': '...'}]`).
                # The `resolve_output_format` hint is crucial for context-dependent formatting.
                resolved_payload = self.resolver.resolve(
                    param_name, param_value, output_format=resolve_output_format
                )

                # --- 2b. NORMALIZE Current and Desired States ---
                # Get the current value from the existing resource.
                compare_key = action_info.get("compare_key", param_name)
                resource_value = self.resource.get(compare_key)

                # This logic filters the resource's current state to only include keys
                # that the user has explicitly provided in their playbook. This ensures
                # that omitted optional keys do not trigger a false change detection.
                if (
                    isinstance(param_value, list)
                    and param_value
                    and isinstance(resource_value, list)
                    and resource_value
                    and isinstance(param_value[0], dict)
                    and isinstance(resource_value[0], dict)
                ):
                    user_provided_keys = set()
                    for item in param_value:
                        if isinstance(item, dict):
                            user_provided_keys.update(item.keys())

                    if user_provided_keys:
                        temp_filtered_list = []
                        for resource_item in resource_value:
                            if isinstance(resource_item, dict):
                                filtered_item = {
                                    k: v
                                    for k, v in resource_item.items()
                                    if k in user_provided_keys
                                }
                                temp_filtered_list.append(filtered_item)
                            else:
                                temp_filtered_list.append(resource_item)
                        # The original resource_value is replaced with the filtered one for comparison.
                        resource_value = temp_filtered_list

                # Get the list of keys that define an object's identity for normalization.
                idempotency_keys = action_info.get("idempotency_keys", [])

                # **CRITICAL EDGE CASE**: Handle schema mismatch between user input and resource state.
                # This occurs when the user provides a simple list of strings (e.g., security group URLs),
                # but the API resource represents them as a rich list of objects. We must transform
                # the resource's rich list into a simple one before normalization can work correctly.
                is_simple_list_payload = (
                    isinstance(resolved_payload, list)
                    and resolved_payload
                    and not isinstance(resolved_payload[0], dict)
                )
                is_complex_list_resource = (
                    isinstance(resource_value, list)
                    and resource_value
                    and isinstance(resource_value[0], dict)
                )

                # Extract the defaults_map from the context.
                defaults_map = action_info.get("defaults_map")

                if is_simple_list_payload and is_complex_list_resource:
                    # A mismatch is detected. Transform the "rich" list from the
                    # resource into a simple list of URLs for a fair comparison.
                    transformed_resource_value = [
                        item.get("url")
                        for item in resource_value
                        if item.get("url") is not None
                    ]
                    # Now, normalize the newly transformed (simple) list.
                    normalized_old = self._normalize_for_comparison(
                        transformed_resource_value, [], defaults_map
                    )
                else:
                    # In all other cases (object-to-object, etc.), no pre-transformation
                    # is needed before normalization.
                    normalized_old = self._normalize_for_comparison(
                        resource_value, idempotency_keys, defaults_map
                    )

                # Normalize the user's desired state.
                normalized_new = self._normalize_for_comparison(
                    resolved_payload, idempotency_keys, defaults_map
                )

                # --- 2c. DETECT Change ---
                # The actual idempotency check: a simple, reliable comparison of the two normalized values.
                if normalized_new != normalized_old:
                    # --- 2d. GENERATE Command ---
                    # A change was detected. We must create an `ActionCommand` for it.

                    # **CRITICAL EDGE CASE**: Handle API payload wrapping.
                    # Some action endpoints expect a raw JSON body (e.g., `[...]`), while
                    # others expect it to be wrapped in an object (e.g., `{"rules": [...]}`).
                    # The generator infers this and provides the 'wrap_in_object' flag.
                    if action_info.get("wrap_in_object"):
                        final_api_payload = {param_name: resolved_payload}
                    else:
                        final_api_payload = resolved_payload

                    # Build wait_config for this action if the module is configured for it.
                    wait_config = None
                    if self.context.get("wait_config"):
                        wait_config = self.context["wait_config"].copy()
                        wait_config["polling_path"] = self.context[
                            "resource_detail_path"
                        ]
                        wait_config["uuid_source"] = {
                            "location": "resource",
                            "key": "uuid",
                        }

                    # Instantiate the `ActionCommand` with all necessary information.
                    commands.append(
                        Command(
                            self,
                            method="POST",
                            path=action_info["path"],
                            command_type="action",
                            data=final_api_payload,
                            path_params={"uuid": self.resource["uuid"]},
                            description=f"Execute action '{param_name}' on {self.context['resource_type']}",
                            wait_config=wait_config,
                        )
                    )

        # --- Step 3: Return the Plan ---
        # Return the list of generated commands. This list will be empty if no
        # actions needed to be triggered.
        return commands

    def check_existence(self):
        """
        A generic, configurable method to check if a resource exists.

        This method serves as the single source of truth for existence checks
        for all runner types. It is driven by keys in the runner's context,
        allowing for flexible configuration.

        It populates `self.resource` with the found data or sets it to `None`.

        Required context keys:
        - `check_url` (str): The API list endpoint to query.

        Optional context keys:
        - `check_filter_keys` (dict): A mapping of Ansible parameter names to the
                                      API query filter keys they correspond to
                                      (e.g., `{"project": "project_uuid"}`).
        """
        # --- Step 1: Gather configuration from the context ---
        check_url = self.context["check_url"]

        # --- Step 2: Build the query parameters ---
        # Start with the primary identifier (e.g., 'name_exact').
        identifier_value = self.module.params["name"]
        query_params = {"name_exact": identifier_value}

        # Add any additional context filters (e.g., project_uuid).
        filter_keys = self.context.get("check_filter_keys", {})
        for param_name, filter_key in filter_keys.items():
            if self.module.params.get(param_name):
                # Use the resolver to convert the context param (e.g., project name)
                # into its UUID for the API filter.
                resolved_url = self.resolver.resolve_to_url(
                    param_name=param_name, value=self.module.params[param_name]
                )
                if resolved_url:
                    query_params[filter_key] = resolved_url.strip("/").split("/")[-1]

        # --- Step 3: Execute the API call ---
        data, _ = self.send_request("GET", check_url, query_params=query_params)

        # --- Step 4: Process the result ---
        if data and len(data) > 1:
            self.module.fail_json(
                msg=f"Multiple resources found for '{identifier_value}'. The first one will be used."
            )

        # Handle both list responses and direct object responses gracefully.
        if isinstance(data, list):
            self.resource = data[0] if data else None
        else:
            self.resource = data if isinstance(data, dict) else None

    def _apply_defaults(self, item: dict, defaults_map: dict) -> dict:
        """
        Normalizes a single dictionary item by applying default values for any
        keys that are missing from the item.
        """
        # Start with a copy to avoid modifying the original object.
        normalized_item = item.copy()

        # If no defaults are configured, return immediately.
        if not defaults_map:
            return normalized_item

        # Iterate through the pre-processed defaults map.
        for key, default_value in defaults_map.items():
            # If a key is missing from the item...
            if key not in normalized_item:
                # ...add it with its default value.
                normalized_item[key] = default_value
        return normalized_item
