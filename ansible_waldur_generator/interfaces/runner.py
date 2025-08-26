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

    def _normalize_for_comparison(self, value: any, idempotency_keys: list[str]) -> any:
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

                # This is the core of the complex normalization. We create a new, temporary
                # dictionary containing ONLY the keys that define the object's identity.
                # This ensures we ignore transient or server-generated fields (like 'uuid'
                # or 'status') when comparing the user's desired state to the current state.
                filtered_item = {key: item.get(key) for key in idempotency_keys}

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

    def _handle_simple_updates(self):
        """
        A generic handler for simple, direct attribute updates via a PATCH request.

        This method is responsible for the most common type of update operation:
        changing basic fields like 'name', 'description', 'ram', etc., that are
        directly supported by the resource's primary update endpoint (usually
        configured to accept a PATCH method).

        The core workflow is as follows:
        1.  **Identify Updatable Fields:** It reads a list of field names from the
            runner's context. This list is generated by the plugin and defines which
            Ansible parameters correspond to mutable fields on the resource.
        2.  **Detect Changes:** It iterates through this list and compares the value
            provided by the user in the Ansible playbook with the current value on
            the existing resource. This is the idempotency check.
        3.  **Build a Payload:** It constructs a payload dictionary containing *only*
            the fields that have actually changed. This is crucial for a clean
            PATCH request and avoids sending unnecessary data.
        4.  **Execute the Update:** If and only if the payload is non-empty (meaning
            at least one change was detected), it sends a PATCH request to the
            resource's update endpoint.
        5.  **Update Local State:** After a successful update, it merges the response
            from the API back into the runner's local representation of the resource
            (`self.resource`) to ensure it reflects the new state.

        This method is designed to be called by specialized runners (`CrudRunner`,
        `OrderRunner`) as part of their overall `update()` orchestration.
        """
        # --- Step 0: Initial Setup and Guard Clauses ---

        # Retrieve the necessary configuration from the runner's context.
        # `update_path`: The URL template for the resource's update endpoint
        #                (e.g., "/api/openstack-instances/{uuid}/").
        # `update_fields`: A list of Ansible parameter names that are considered
        #                  mutable for this resource (e.g., ["description", "name"]).
        update_path = self.context.get("update_path")
        update_fields = self.context.get("update_fields", [])

        # If there is no existing resource to update, no configured update endpoint,
        # or no fields are defined as updatable, then there is nothing to do.
        # This prevents errors and unnecessary processing.
        if not (self.resource and update_path and update_fields):
            return

        # --- Step 1: Detect Changes and Build the PATCH Payload ---

        # Initialize an empty dictionary to hold only the parameters that need to be changed.
        update_payload = {}

        # Iterate through each field that the module configuration has marked as updatable.
        for field in update_fields:
            # Get the value for this field from the user's Ansible playbook parameters.
            param_value = self.module.params.get(field)

            # The idempotency check happens here. We only consider a field for an update if:
            #   a) The user has actually provided a value for it (`param_value is not None`).
            #      This prevents the module from trying to set a field to `null` just because
            #      the user omitted it from their playbook.
            #   b) The user-provided value is different from the value currently on the
            #      resource in Waldur.
            if param_value is not None and param_value != self.resource.get(field):
                # A change has been detected. Add the field and its new value to the payload.
                update_payload[field] = param_value

        # --- Step 2: Execute the Update Request (If Necessary) ---

        # Only proceed if the `update_payload` is not empty. If it's empty, it means
        # all user-provided values matched the existing resource's state, and the
        # module is perfectly idempotent. No API call is needed.
        if update_payload:
            # A change is required. Send the PATCH request to the API.
            # The `path_params` argument will substitute the `{uuid}` placeholder in the
            # `update_path` with the actual UUID of the resource we are updating.
            updated_resource, _ = self._send_request(
                "PATCH",
                update_path,
                data=update_payload,
                path_params={"uuid": self.resource["uuid"]},
            )

            # --- Step 3: Update Local State and Flag Change ---

            # After a successful PATCH, the API typically returns the updated representation
            # of the resource. We merge this new data into our local `self.resource` object.
            # This is important so that if any subsequent actions in the same run need to
            # check the resource's state, they see the most current version.
            if updated_resource:
                self.resource.update(updated_resource)

            # Set the global `has_changed` flag to True. This tells Ansible that the module
            # made a change to the system, which is crucial for playbook reporting.
            self.has_changed = True

    def _handle_action_updates(self, resolve_output_format="create"):
        """
        A generic, powerful engine for executing complex, idempotent, action-based updates.

        This method orchestrates the entire "resolve -> normalize -> compare -> execute"
        workflow for all special update actions defined in a module's configuration.
        It is designed to be called by specialized runners (`CrudRunner`, `OrderRunner`)
        after they have performed any necessary context-specific setup (like cache priming).

        The core responsibilities of this engine are:
        1.  **Iterate** through all configured update actions.
        2.  **Resolve** user-friendly inputs (e.g., names) into the precise data structures
            required by the API, handling nested values.
        3.  **Perform a robust, order-insensitive idempotency check** by comparing the
            normalized desired state with the normalized current state of the resource. This
            includes handling tricky edge cases where the format of the desired state
            (e.g., a list of strings) differs from the resource's state (e.g., a list of objects).
        4.  **Execute** the API call (a POST to a special action endpoint) only if a
            change is actually detected. This includes correctly formatting the request
            body, which may need to be a raw list or a wrapped JSON object.
        5.  **Handle asynchronous operations** by correctly identifying HTTP 202 status
            codes and triggering a wait/polling mechanism.
        6.  **Ensure data consistency** by triggering a final re-fetch of the resource's
            state if any synchronous changes were made.

        Args:
            resolve_output_format (str):
                A hint passed directly to the `ParameterResolver`. This is a crucial
                parameter for flexibility, allowing the same user parameter (e.g.,
                `security_groups`) to be formatted differently depending on the context.
                For example, a 'create' order might need `[{'url': '...'}]`, while an
                'update_action' might need a simple list of UUIDs `['uuid1', ...]`.
                Defaults to "create".
        """
        # --- Step 0: Initial Setup and Guard Clauses ---

        # Retrieve the dictionary of configured actions from the runner's context.
        # This context is pre-processed by the generator's plugin.
        update_actions = self.context.get("update_actions", {})

        # If there's no existing resource to update or no actions are configured,
        # there is nothing to do. Exit immediately.
        if not (self.resource and update_actions):
            return

        # This flag tracks whether any synchronous (non-202) actions were performed.
        # If true, it will trigger a single, efficient re-fetch of the resource's
        # state at the very end to ensure the data returned to the user is up-to-date.
        needs_refetch = False

        # --- Step 1: Main Loop - Process Each Action ---

        for _, action_info in update_actions.items():
            # Extract the configuration for the current action.
            param_name = action_info["param"]
            param_value = self.module.params.get(param_name)

            # An action is only triggered if the user has provided its corresponding parameter.
            # If the parameter is `None`, we skip this action entirely.
            if param_value is not None:
                # --- Step 2: RESOLVE - Convert User Input to API-Ready Data ---
                # This is a critical step. We delegate to the powerful ParameterResolver,
                # which recursively traverses the user's input (`param_value`) and converts
                # all user-friendly names or UUIDs into the final API URLs or other required
                # data structures. The `resolve_output_format` hint ensures the final
                # structure is correct for this specific action's API endpoint.
                resolved_payload = self.resolver.resolve(
                    param_name, param_value, output_format=resolve_output_format
                )

                # --- Step 3: NORMALIZE & COMPARE - The Idempotency Check ---
                # This is the heart of the idempotency logic, including critical edge case handling.

                # Get the current value from the existing resource. The `compare_key` tells
                # us which field on the resource corresponds to this action's parameter.
                resource_value = self.resource.get(action_info["compare_key"])

                # Get the list of keys that define an object's identity. This is essential
                # for correctly comparing lists of complex objects.
                idempotency_keys = action_info.get("idempotency_keys", [])

                #
                # Dual-mode normalization
                #
                # This block handles the difficult but common case where the existing resource
                # represents a relationship with a "rich" list of objects (e.g., `[{'name': 'sg1', 'url': '...'}]`),
                # but the user's desired state resolves to a "simple" list of strings (e.g., `['url1', 'url2']`).
                # A direct normalization of both would lead to an incorrect comparison.
                #
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

                if is_simple_list_payload and is_complex_list_resource:
                    # A mismatch is detected. We must transform the "rich" list from the
                    # resource into a simple list so it can be compared. By strong convention,
                    # we assume the key to extract for this transformation is 'url'.
                    transformed_resource_value = [
                        item.get("url")
                        for item in resource_value
                        if item.get("url") is not None
                    ]
                    # Now, normalize the newly transformed list (which is simple).
                    normalized_old = self._normalize_for_comparison(
                        transformed_resource_value, []
                    )
                else:
                    # In all other cases (object-to-object, string-to-string, etc.), no
                    # pre-transformation is needed before normalization.
                    normalized_old = self._normalize_for_comparison(
                        resource_value, idempotency_keys
                    )

                # Normalize the user's desired state.
                normalized_new = self._normalize_for_comparison(
                    resolved_payload, idempotency_keys
                )

                # The actual idempotency check: a simple, reliable comparison of the two normalized values.
                if normalized_new != normalized_old:
                    # --- Step 4: EXECUTE - A Change Was Detected ---
                    # The state is not what the user wants it to be, so we must act.

                    #
                    # Conditional payload wrapping
                    #
                    # Some API action endpoints expect a raw JSON body (e.g., just a list `[...]`),
                    # while others expect the payload to be wrapped in a JSON object
                    # (e.g., `{"param_name": [...]}`). The plugin analyzes the API schema and
                    # provides the 'wrap_in_object' flag in the context. We must respect it here.
                    #
                    if action_info.get("wrap_in_object"):
                        # API expects: {"param_name": <resolved_payload>}
                        final_api_payload = {param_name: resolved_payload}
                    else:
                        # API expects the raw payload (e.g., a list of strings).
                        final_api_payload = resolved_payload

                    # Send the POST request to the action's specific API endpoint.
                    _, status_code = self._send_request(
                        "POST",
                        action_info["path"],
                        data=final_api_payload,
                        path_params={"uuid": self.resource["uuid"]},
                    )

                    # Mark that a change has occurred in the system.
                    self.has_changed = True

                    # --- Step 5: WAIT - Handle Asynchronous Responses ---
                    # Check if the API responded with HTTP 202 Accepted, which indicates
                    # that the task was started but is not yet complete.
                    if (
                        status_code == 202
                        and self.module.params.get("wait", True)
                        and self.context.get("wait_config")
                    ):
                        # If waiting is enabled, block execution and poll the resource's
                        # state until it becomes stable (e.g., 'OK' or 'Erred').
                        # The `_wait_for_resource_state` method updates `self.resource` internally.
                        self._wait_for_resource_state(self.resource["uuid"])
                    else:
                        # For synchronous actions (e.g., HTTP 200, 201, 204), the change
                        # was immediate. We set the flag to perform a single re-fetch
                        # after all actions are processed.
                        needs_refetch = True

        # --- Step 6: RE-FETCH - Ensure Final State Consistency ---
        # After the loop has finished, if any synchronous actions were performed,
        # `self.resource` is now out of date. We call `check_existence()` one last
        # time to get the absolute final state of the resource before exiting the module.
        if needs_refetch:
            self.check_existence()
