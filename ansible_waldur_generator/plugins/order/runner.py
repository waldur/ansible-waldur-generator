from copy import deepcopy
import time

from ansible_waldur_generator.interfaces.runner import BaseRunner


class OrderRunner(BaseRunner):
    """
    A runner for Ansible modules that manage resources via Waldur's standard
    asynchronous marketplace order workflow.

    This runner encapsulates the entire lifecycle logic:
    - Checking for the resource's existence.
    - Creating a resource via a marketplace order if it's absent.
    - Updating a resource's simple attributes if it's present and has changed.
    - Terminating a resource via the marketplace if it's marked as absent.
    - Polling for order completion.
    - Handling complex parameter resolution, including dependent filters and lists.
    """

    def __init__(self, module, context):
        """
        Initializes the base class and sets the initial state of the resource.
        """
        super().__init__(module, context)
        # self.resource will store the current state of the Waldur resource,
        # or None if it does not exist. It is populated by check_existence().
        self.resource = None
        # This will cache resolved API responses to avoid redundant lookups.
        self.resolved_api_responses = {}

    def run(self):
        """
        The main execution entry point that orchestrates the entire module lifecycle.
        This method follows the standard Ansible module pattern of ensuring a
        desired state (present or absent).
        """
        # Step 1: Determine the current state of the resource in Waldur.
        self.check_existence()

        # Step 2: Handle Ansible's --check mode. If enabled, we predict changes
        # without making any modifying API calls and exit early.
        if self.module.check_mode:
            self.handle_check_mode()
            return

        # Step 3: Execute actions based on the resource's current state and the
        # user's desired state.
        if self.resource:
            # The resource currently exists.
            if self.module.params["state"] == "present":
                # Desired: present, Current: present -> Check for updates.
                self.update()
            elif self.module.params["state"] == "absent":
                # Desired: absent, Current: present -> Delete the resource.
                self.delete()
        else:
            # The resource does not currently exist.
            if self.module.params["state"] == "present":
                # Desired: present, Current: absent -> Create the resource.
                self.create()
            # If Desired: absent, Current: absent, we do nothing.

        # Step 4: Format the final response and exit the module.
        self.exit()

    def check_existence(self):
        """
        Checks if a resource exists by querying the configured `existence_check_url`.

        It filters the query by the resource `name` and any context parameters,
        such as the `project`, to uniquely identify the resource.
        """
        # Start with a mandatory filter for an exact name match.
        params = {"name_exact": self.module.params["name"]}

        # Add any additional filters defined in the context (e.g., project_uuid).
        filter_keys = self.context.get("existence_check_filter_keys", {})
        for param_name, filter_key in filter_keys.items():
            if self.module.params.get(param_name):
                # Resolve the user-provided name/UUID (e.g., project name) to its URL
                # to extract the UUID for the filter.
                resolved_url = self._resolve_to_url(
                    path=self.context["resolvers"][param_name]["url"],
                    value=self.module.params[param_name],
                    error_message=self.context["resolvers"][param_name][
                        "error_message"
                    ],
                )
                if resolved_url:
                    # Extract the UUID from the end of the resolved URL.
                    params[filter_key] = resolved_url.strip("/").split("/")[-1]

        # Send the API request to check for the resource.
        data = self._send_request(
            "GET",
            self.context["existence_check_url"],
            query_params=params,
        )

        if data and len(data) > 1:
            self.module.warn(
                f"Multiple resources found for '{self.module.params['name']}'. The first one will be used."
            )

        # Store the first result found, or None if the list is empty.
        self.resource = data[0] if data else None

    def create(self):
        """
        Creates a new resource by submitting a marketplace order. This involves
        resolving all necessary parameters into API URLs and constructing the
        order payload.
        """
        # Resolve top-level required parameters first to satisfy dependencies.
        project_url = self._resolve_parameter("project", self.module.params["project"])
        offering_url = self._resolve_parameter(
            "offering", self.module.params["offering"]
        )

        # Build the 'attributes' dictionary for the order payload.
        attributes = {"name": self.module.params["name"]}
        for key in self.context["attribute_param_names"]:
            if key in self.module.params and self.module.params[key] is not None:
                # Recursively resolve the entire parameter structure.
                attributes[key] = self._resolve_parameter(key, self.module.params[key])

        order_payload = {
            "project": project_url,
            "offering": offering_url,
            "plan": self.module.params.get("plan"),
            "limits": self.module.params.get("limits", {}),
            "attributes": attributes,
            "accepting_terms_of_service": True,
        }

        # Send the request to create the order.
        order = self._send_request(
            "POST", "/api/marketplace-orders/", data=order_payload
        )

        # If waiting is enabled, poll the order's status until completion.
        if self.module.params.get("wait", True) and order:
            self._wait_for_order(order["uuid"])

        self.has_changed = True

    def update(self):
        """
        Updates an existing resource if its configuration has changed. This method
        only handles simple, direct attribute updates (e.g., via PATCH).
        """
        # Do nothing if no update endpoint is configured for this resource.
        if not self.context.get("update_url"):
            return

        # --- Proactive Dependency Resolution for Actions ---
        # Before checking for updates, we must populate the dependency cache
        # (`self.resolved_api_responses`). This is crucial for any nested
        # resolvers within update actions that use `filter_by` (e.g., resolving
        # a 'subnet' needs to know the 'offering's scope_uuid).
        # We fetch the data for top-level dependencies from the existing resource's URLs.
        if self.resource:
            # These are the most common dependencies for filtering.
            dependencies_to_resolve = ["offering", "project"]
            for dep_name in dependencies_to_resolve:
                if (
                    self.resource.get(dep_name)
                    and dep_name not in self.resolved_api_responses
                ):
                    # Fetch the full object from its URL and cache it.
                    dep_data = self._send_request("GET", self.resource[dep_name])
                    self.resolved_api_responses[dep_name] = dep_data

        update_payload = {}
        # Iterate through the fields that are configured as updatable.
        for field in self.context["update_check_fields"]:
            param_value = self.module.params.get(field)
            if self.resource:
                resource_value = self.resource.get(field)
                # If the user-provided value is different from the existing value,
                # add it to the update payload.
                if param_value is not None and param_value != resource_value:
                    update_payload[field] = param_value

        # If there are changes to apply, send the PATCH request.
        if update_payload and self.resource:
            path = self.context["update_url"]
            self.resource = self._send_request(
                "PATCH",
                path,
                data=update_payload,
                path_params={"uuid": self.resource["uuid"]},
            )
            self.has_changed = True

        # 2. Handle complex, idempotent, action-based updates (e.g., updating ports).
        update_actions = self.context.get("update_actions", {})
        for _, action_info in update_actions.items():
            param_name = action_info["param"]
            compare_key = action_info["compare_key"]
            param_value = self.module.params.get(param_name)

            # Perform the idempotency check ONLY if the user provided the parameter.
            if param_value is not None:
                resource_value = self.resource.get(compare_key)
                # If the user-provided structure differs from the current state...
                if param_value != resource_value:
                    # ...resolve the user's payload before sending it.
                    # This converts all names/UUIDs (e.g., in subnets) to API URLs,
                    # respecting all `filter_by` rules from the main resolvers.
                    resolved_payload = self._resolve_parameter(param_name, param_value)

                    self._send_request(
                        "POST",
                        action_info["path"],
                        data=resolved_payload,
                        path_params={"uuid": self.resource["uuid"]},
                    )
                    self.has_changed = True
                    # After a complex action, the resource state might have changed.
                    # Re-fetch it to ensure the returned data is accurate.
                    self.check_existence()

    def delete(self):
        """
        Terminates the resource by calling the marketplace termination endpoint.
        """
        if self.resource:
            # The API requires using the resource's specific 'marketplace_resource_uuid'
            # for termination actions.
            uuid_to_terminate = self.resource["marketplace_resource_uuid"]
            path = f"/api/marketplace-resources/{uuid_to_terminate}/terminate/"
            self._send_request("POST", path, data={})
            self.has_changed = True
            # After termination, the resource is considered gone.
            self.resource = None

    def _wait_for_order(self, order_uuid):
        """
        Polls a marketplace order until it reaches a terminal state (done, erred, etc.).
        """
        timeout = self.module.params.get("timeout", 600)
        interval = self.module.params.get("interval", 20)
        start_time = time.time()

        while time.time() - start_time < timeout:
            order = self._send_request("GET", f"/api/marketplace-orders/{order_uuid}/")

            if order and order["state"] == "done":
                # CRITICAL: After the order completes, the resource has been created.
                # We must re-fetch its final state to return accurate data to the user.
                self.check_existence()
                return
            if order and order["state"] in ["erred", "rejected", "canceled"]:
                self.module.fail_json(
                    msg=f"Order finished with status '{order['state']}'. Error message: {order.get('error_message')}"
                )

            time.sleep(interval)

        self.module.fail_json(
            msg=f"Timeout waiting for order {order_uuid} to complete."
        )

    def handle_check_mode(self):
        """
        Predicts changes for Ansible's --check mode without making any API calls.
        """
        state = self.module.params["state"]
        if state == "present" and not self.resource:
            self.has_changed = True  # Predicts creation.
        elif state == "absent" and self.resource:
            self.has_changed = True  # Predicts deletion.
        elif state == "present" and self.resource and self.context.get("update_url"):
            # Predicts if any updatable fields have changed.
            for field in self.context["update_check_fields"]:
                param_value = self.module.params.get(field)
                if self.resource:
                    resource_value = self.resource.get(field)
                    if param_value is not None and param_value != resource_value:
                        self.has_changed = True
                        break
            # Predicts if any action-based updates would trigger.
            if not self.has_changed:
                for action_info in self.context.get("update_actions", {}).values():
                    param_value = self.module.params.get(action_info["param"])
                    if self.resource:
                        resource_value = self.resource.get(action_info["compare_key"])
                        if param_value is not None and param_value != resource_value:
                            self.has_changed = True
                            break
        self.exit()

    def exit(self):
        """
        Formats the final response and exits the module execution.
        """
        self.module.exit_json(changed=self.has_changed, resource=self.resource)

    def _resolve_single_value(
        self, param_name: str, value: any, resolver_conf: dict
    ) -> any:
        """
        Resolves a single primitive value (e.g., a name string or a UUID string)
        into its final, API-ready representation. This function is the heart of
        the resolution process, handling the actual API lookups and data formatting.

        Its responsibilities are:
        1. Building dependency filters (e.g., finding the 'tenant_uuid' from the
           'offering' to correctly filter a list of subnets).
        2. Sending the API request to find the resource by name or UUID.
        3. Handling cases where zero or multiple resources are found.
        4. Caching the full API response of the resolved object for future
           dependency lookups.
        5. Formatting the final return value into either a direct URL (for simple
           resolvers) or a structured dictionary (for list-based resolvers like
           security groups, which require `{'url': ...}`).

        Args:
            param_name (str): The name of the parameter being resolved (e.g., "subnet").
            value (any): The primitive value provided by the user (e.g., "private-subnet-A").
            resolver_conf (dict): The full configuration for this resolver from the context.

        Returns:
            any: The resolved and formatted value, ready to be included in the API payload.
        """
        # Step 1: Build a dictionary of query parameters needed to filter this lookup,
        # based on the `filter_by` dependencies defined in the generator config.
        query_params = self._build_dependency_filters(
            param_name, resolver_conf.get("filter_by", []), self.resolved_api_responses
        )

        # Step 2: Perform the API lookup. This helper function intelligently handles
        # both direct UUID lookups and filtered name-based searches.
        resource_list = self._resolve_to_list(
            path=resolver_conf["url"],
            value=value,
            query_params=query_params,
        )

        # Step 3: Handle API responses.
        if not resource_list:
            # If no resource is found, fail with a user-friendly error message.
            self.module.fail_json(
                msg=resolver_conf["error_message"].format(value=value)
            )
        if len(resource_list) > 1:
            # If multiple resources match a name, warn the user and proceed with the first one.
            self.module.warn(
                f"Multiple resources found for '{value}' for parameter '{param_name}'. Using the first one."
            )

        # The definitive object found by the API.
        resolved_object = resource_list[0]

        # Step 4: Cache the full API response object. This is critical for subsequent
        # lookups that may depend on this one (e.g., other resolvers that need data
        # from the 'offering' object).
        # We use a tuple key to distinguish between different resolutions for the same
        # parameter name (e.g., two different subnets in a `ports` list).
        self.resolved_api_responses[(param_name, value)] = resolved_object
        # For top-level parameters, we also cache by name for simpler dependency lookups.
        if param_name in self.module.params:
            self.resolved_api_responses[param_name] = resolved_object

        # Step 5: Format the return value.
        # Check if this resolver is for a list of items (like 'security_groups').
        if resolver_conf.get("is_list"):
            item_key = resolver_conf.get("list_item_key")
            if item_key:
                # If so, format the output as a dictionary, e.g., `{'url': '...'}`.
                return {item_key: resolved_object["url"]}

        # For all other cases (simple foreign keys, nested lookups), return the direct URL.
        return resolved_object["url"]

    def _resolve_parameter(self, param_name: str, param_value: any) -> any:
        """
        Recursively traverses a parameter's value structure (which can be a
        dictionary, a list, or a primitive) and resolves any fields that have
        a configured resolver.

        This function acts as a "walker" or "traversal engine." It understands
        the shape of the data but delegates the actual work of API lookups
        to `_resolve_single_value`.

        Its responsibilities are:
        1. Determining if a value is a dictionary, list, or primitive.
        2. Recursing into dictionaries and lists to process their contents.
        3. Identifying when a primitive value needs to be resolved by checking for a
           matching resolver configuration.
        4. Distinguishing between a "list of resolvable items" (like security_groups,
           where each item is a name to be looked up) and a "list of complex objects"
           (like ports, where each item is a dictionary that needs to be recursed into).

        Args:
            param_name (str): The name of the current parameter context (e.g., "ports").
            param_value (any): The data structure provided by the user for this parameter.

        Returns:
            any: The fully resolved data structure, with all names/UUIDs replaced by
                 the API-ready, formatted values.
        """
        # Get the resolver configuration for the current parameter context.
        resolver_conf = self.context["resolvers"].get(param_name)

        # Case 1: The value is a dictionary (e.g., a single item from a `ports` list).
        if isinstance(param_value, dict):
            # Create a deep copy to avoid modifying the user's original data.
            resolved_dict = deepcopy(param_value)
            # Iterate through the dictionary's items.
            for key, value in param_value.items():
                # Recurse, using the dictionary key as the new `param_name` context.
                # For example, when processing a `port` object, the key might be "subnet",
                # triggering the "subnet" resolver in the next recursive call.
                resolved_dict[key] = self._resolve_parameter(key, value)
            return resolved_dict

        # Case 2: The value is a list.
        if isinstance(param_value, list):
            # Check if there is a resolver for this parameter and if it's marked
            # as a list-based resolver (e.g., for `security_groups`).
            if resolver_conf and resolver_conf.get("is_list"):
                # This is a list of simple values (names/UUIDs) that each need to be resolved.
                # We call `_resolve_single_value` on each item in the list.
                return [
                    self._resolve_single_value(param_name, item, resolver_conf)
                    for item in param_value
                ]
            else:
                # This is a list of complex objects (like `ports`).
                # We recurse into each item, maintaining the original `param_name` context.
                return [
                    self._resolve_parameter(param_name, item) for item in param_value
                ]

        # Case 3: The value is a primitive (string, int, etc.).
        # Check if a resolver exists for the current parameter name.
        if resolver_conf:
            # If a resolver exists, delegate the work to `_resolve_single_value`.
            return self._resolve_single_value(param_name, param_value, resolver_conf)

        # Base Case: The value is a primitive and has no resolver. Return it as is.
        return param_value

    def _build_dependency_filters(
        self, name, dependencies, resolved_api_responses
    ) -> dict:
        """Builds a query parameter dictionary from resolver dependencies."""
        query_params = {}
        for dep in dependencies:
            source_param = dep["source_param"]
            if source_param not in resolved_api_responses:
                self.module.fail_json(
                    msg=f"Configuration error: Resolver for '{name}' depends on '{source_param}', which has not been resolved yet."
                )
            source_value = resolved_api_responses[source_param].get(dep["source_key"])
            if source_value is None:
                self.module.fail_json(
                    msg=f"Could not find key '{dep['source_key']}' in the response for '{source_param}'."
                )
            query_params[dep["target_key"]] = source_value
        return query_params

    def _resolve_to_list(self, path, value, query_params=None) -> list:
        """
        A helper to resolve a name or UUID to a list of matching resources,
        applying any provided query filters.
        """
        # If the value is a UUID, we can fetch it directly for efficiency.
        if self._is_uuid(value):
            # We ignore query_params here as direct fetch is more specific.
            resource = self._send_request("GET", f"{path}{value}/")
            return [resource] if resource else []

        # If it's a name, we add it to the query parameters and search.
        final_query = query_params.copy() if query_params else {}
        final_query["name"] = value
        return self._send_request("GET", path, query_params=final_query)
