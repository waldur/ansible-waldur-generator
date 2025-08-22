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
        self.exit()

    def exit(self):
        """
        Formats the final response and exits the module execution.
        """
        self.module.exit_json(changed=self.has_changed, resource=self.resource)

    def _resolve_parameter(self, param_name: str, param_value: any) -> any:
        """
        Recursively resolves a parameter value. It handles strings, lists, and dicts,
        looking for keys that match a configured resolver.
        """
        # If the value is a dictionary, traverse its keys.
        if isinstance(param_value, dict):
            # Make a deep copy to avoid modifying the original params.
            resolved_dict = deepcopy(param_value)
            for key, value in param_value.items():
                resolved_dict[key] = self._resolve_parameter(key, value)
            return resolved_dict

        # If the value is a list, traverse its items.
        if isinstance(param_value, list):
            return [self._resolve_parameter(param_name, item) for item in param_value]

        # Base case: The value is a primitive (string, int, etc.)
        resolver_conf = self.context["resolvers"].get(param_name)
        if not resolver_conf:
            return param_value  # No resolver for this param, return as is.

        # --- A resolver exists, perform the resolution ---
        query_params = self._build_dependency_filters(
            param_name, resolver_conf.get("filter_by", []), self.resolved_api_responses
        )
        resource_list = self._resolve_to_list(
            path=resolver_conf["url"],
            value=param_value,
            query_params=query_params,
        )

        if not resource_list:
            self.module.fail_json(
                msg=resolver_conf["error_message"].format(value=param_value)
            )
        if len(resource_list) > 1:
            self.module.warn(
                f"Multiple resources found for '{param_value}' for parameter '{param_name}'. Using the first one."
            )

        resolved_object = resource_list[0]
        # Cache the full response for dependency lookups.
        # Use a tuple of (name, value) as key to distinguish different resolutions
        # for the same parameter type (e.g., two different subnets).
        self.resolved_api_responses[(param_name, param_value)] = resolved_object
        # Cache top-level parameter responses for dependency lookups by name only.
        if param_name in self.module.params:
            self.resolved_api_responses[param_name] = resolved_object

        # If it's a list-based resolver, package the URL into the required structure.
        if resolver_conf.get("is_list"):
            item_key = resolver_conf.get("list_item_key")
            if item_key:
                return {item_key: resolved_object["url"]}
        return resolved_object["url"]

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
