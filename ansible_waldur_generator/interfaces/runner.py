from abc import abstractmethod
import json
import time
import uuid
from urllib.parse import urlencode

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.urls import fetch_url

from .command import ActionCommand, CreateCommand, DeleteCommand, UpdateCommand


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

    def execute_change_plan(self, plan: list):
        """
        Executes a list of Command objects, making the actual API calls.
        This is the "execution" phase.
        """
        if not plan:
            return

        self.has_changed = True
        needs_refetch = False

        for command in plan:
            result = command.execute()

            # Correctly update self.resource after command execution.
            if isinstance(command, CreateCommand):
                self.resource = result
            elif isinstance(command, UpdateCommand):
                # An update command can return a partial or full resource.
                # Merge the result to ensure we have the most complete state.
                if self.resource and result:
                    self.resource.update(result)
            elif isinstance(command, DeleteCommand):
                self.resource = None  # The resource is now gone.
            elif isinstance(command, ActionCommand):
                # Handle async actions
                if (
                    result == 202
                    and self.module.params.get("wait", True)
                    and self.context.get("wait_config")
                ):
                    self._wait_for_resource_state(self.resource["uuid"])
                else:
                    needs_refetch = True

        if needs_refetch:
            self.check_existence()

    def handle_check_mode(self, plan: list):
        """
        Generates a predictive diff from a change plan and exits.
        """
        if plan:
            self.has_changed = True
        # The specialized runner's exit method will handle the diff.
        self.exit(diff=[cmd.to_diff() for cmd in plan])

    def send_request(
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
            resource_state, status_code = self.send_request(
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
            return [
                UpdateCommand(
                    self,
                    update_path,
                    changes,  # Pass the full list of changes for detailed diffing.
                    path_params={"uuid": self.resource["uuid"]},
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

                    # Instantiate the `ActionCommand` with all necessary information.
                    commands.append(
                        ActionCommand(
                            self,
                            action_info["path"],
                            final_api_payload,
                            param_name,
                            old_value=resource_value,  # Store the original, un-normalized old value for the diff.
                            new_value=resolved_payload,  # Store the resolved, un-normalized new value for the diff.
                            path_params={"uuid": self.resource["uuid"]},
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
