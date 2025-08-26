import time

from ansible_waldur_generator.interfaces.resolver import ParameterResolver
from ansible_waldur_generator.interfaces.runner import BaseRunner

# A map of transformation types to their corresponding functions.
# This makes the system easily extendable with new transformations.
TRANSFORMATION_MAP = {
    "gb_to_mb": lambda x: int(x) * 1024,
}


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
    """

    def __init__(self, module, context):
        """
        Initializes the base class and sets the initial state of the resource.
        """
        super().__init__(module, context)
        # self.resource will store the current state of the Waldur resource,
        # or None if it does not exist. It is populated by check_existence().
        self.resource = None
        self.order = None

        # An instance of the ParameterResolver is created, passing this runner instance to it.
        # This gives the resolver access to _send_request, the module, and the context.
        # The resolver will now manage its own internal cache, replacing `self.resolved_api_responses`.
        self.resolver = ParameterResolver(self)

    def _apply_transformations(self, payload: dict) -> dict:
        """
        Applies configured value transformations to a payload dictionary.

        Args:
            payload: The dictionary of parameters to transform.

        Returns:
            A new dictionary with the transformed values.
        """
        transformations = self.context.get("transformations", {})
        if not transformations:
            return payload

        transformed_payload = payload.copy()
        for param_name, transform_type in transformations.items():
            if (
                param_name in transformed_payload
                and transformed_payload[param_name] is not None
            ):
                transform_func = TRANSFORMATION_MAP.get(transform_type)
                if transform_func:
                    try:
                        original_value = transformed_payload[param_name]
                        transformed_payload[param_name] = transform_func(original_value)
                    except (ValueError, TypeError):
                        # If conversion fails (e.g., user provides "10GB" instead of 10),
                        # we let it pass. The API validation will catch it and provide a
                        # more user-friendly error than a Python traceback.
                        pass
        return transformed_payload

    def run(self):
        """
        The main execution entry point that orchestrates the entire module lifecycle.
        This method follows the standard Ansible module pattern of ensuring a
        desired state (present or absent).
        """
        # Step 1: Determine the current state of the resource in Waldur.
        self.resource = self.check_existence()

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
                resolved_url = self.resolver.resolve_to_url(
                    param_name=param_name, value=self.module.params[param_name]
                )
                if resolved_url:
                    # Extract the UUID from the end of the resolved URL.
                    params[filter_key] = resolved_url.strip("/").split("/")[-1]

        # Send the API request to check for the resource.
        data, _ = self._send_request(
            "GET",
            self.context["existence_check_url"],
            query_params=params,
        )

        if data and len(data) > 1:
            self.module.warn(
                f"Multiple resources found for '{self.module.params['name']}'. The first one will be used."
            )

        # The _send_request method can return a list (from a list endpoint)
        # or a dict (from a retrieve endpoint). This handles both cases safely.
        if isinstance(data, list):
            return data[0] if data else None
        return data  # It's already a single item or None

    def create(self):
        """
        Creates a new resource by submitting a marketplace order. This involves
        resolving all necessary parameters into API URLs and constructing the
        order payload.
        """
        # --- Resolution Logic Delegation ---
        # First, we resolve the top-level parameters. This is crucial because it populates
        # the resolver's internal cache with the full 'project' and 'offering' objects,
        # making them available for dependency filtering by subsequent resolvers (e.g., for 'flavor' or 'subnet').
        project_url = self.resolver.resolve("project", self.module.params["project"])
        offering_url = self.resolver.resolve("offering", self.module.params["offering"])

        # Build the 'attributes' dictionary for the order payload.
        attributes = {"name": self.module.params["name"]}
        for key in self.context["attribute_param_names"]:
            if key in self.module.params and self.module.params[key] is not None:
                # Recursively resolve the entire parameter structure.
                # Provide the 'create' hint when resolving for the order payload.
                attributes[key] = self.resolver.resolve(
                    key, self.module.params[key], output_format="create"
                )

        # Apply transformations to the attributes before sending to the API.
        transformed_attributes = self._apply_transformations(attributes)

        order_payload = {
            "project": project_url,
            "offering": offering_url,
            "attributes": transformed_attributes,
            "accepting_terms_of_service": True,
        }
        plan = self.module.params.get("plan")
        if plan:
            order_payload.update({"plan": plan})
        limits = self.module.params.get("limits")
        if limits:
            order_payload.update({"limits": limits})

        # Send the request to create the order.
        order, _ = self._send_request(
            "POST", "/api/marketplace-orders/", data=order_payload
        )

        # If waiting is enabled, poll the order's status until completion.
        if self.module.params.get("wait", True) and order:
            self._wait_for_order(order["uuid"])
        self.order = order

        self.has_changed = True

    def update(self):
        """
        Orchestrates the update process for an existing marketplace resource.

        This method is the specialized entry point for handling `state: present` when
        a resource already exists. Its design follows a clear pattern of performing
        context-specific setup before delegating the core execution logic to the
        generic, shared "engine" methods inherited from `BaseRunner`.

        Its specialized responsibilities are crucial for handling the complex
        dependencies inherent in marketplace resources:

        1.  **Cache Priming for Dependency Resolution:** It proactively loads the
            resource's core dependencies (like its `offering` and `project`) into
            the resolver's cache. This is essential for correctly resolving any
            *new* nested parameters the user wants to update (e.g., resolving a new
            `subnet` name requires knowing which tenant to search in, which is
            determined by the `offering`).

        2.  **Cache Overriding for Context Changes:** It allows the user to override
            the primed cache by providing a new `offering` or `project`, ensuring that
            all subsequent parameter resolutions happen within the correct new context.

        After this critical setup is complete, it delegates the actual update
        execution to the generic `_handle_simple_updates` and `_handle_action_updates`
        methods from `BaseRunner`, providing a special hint (`resolve_output_format`)
        to the action handler to ensure API payloads are formatted correctly for
        direct update actions.
        """
        # --- Guard Clause: Ensure a Resource Exists ---
        # The update method is only meaningful if a resource was found during the
        # initial `check_existence()` call. If `self.resource` is `None`, it means
        # the resource doesn't exist, and the `create()` method will be called
        # by the main `run()` logic instead. We can safely exit here.
        if not self.resource:
            return

        # --- Step 1: Handle Simple Field Updates (Delegation) ---
        # First, delegate the entire process of handling simple updates (e.g., 'description')
        # to the generic `_handle_simple_updates` method from `BaseRunner`. This shared
        # method handles the change detection, payload building, and PATCH request.
        self._handle_simple_updates()

        # --- Step 2: Specialized Setup for Marketplace Context ---
        # This block contains the logic that is unique to the OrderRunner and justifies
        # its existence as a specialized class.

        # 2a. Proactively prime the resolver's cache with the resource's key dependencies.
        # We fetch the full API objects for the existing `offering` and `project` using
        # their URLs. This populates the cache, making their attributes (like the offering's
        # `scope_uuid`) available for filtering dependent lookups later on.
        self.resolver.prime_cache_from_resource(self.resource, ["offering", "project"])

        # 2b. Allow user-provided parameters to override the primed cache.
        # If the user specifies a new `offering` in their playbook, we must resolve it
        # immediately. This action overwrites the cached `offering` from the existing
        # resource, ensuring that any subsequent resolutions (e.g., for a new `flavor`
        # or `subnet`) are correctly filtered against the *new* offering's context.
        if self.module.params.get("offering"):
            self.resolver.resolve("offering", self.module.params["offering"])
        # (The same logic could be applied to `project` if needed).

        # --- Step 3: Handle Complex, Action-Based Updates (Delegation) ---
        # With the cache now correctly primed and/or overridden, we can safely delegate
        # the execution of complex updates to the generic `_handle_action_updates` engine.

        # We provide a crucial hint, `resolve_output_format="update_action"`. This tells
        # the ParameterResolver to format the data according to the needs of the direct
        # "update action" API endpoint, which may differ from the format required by the
        # "create order" endpoint. For example, an update action for security groups might
        # expect a raw list of UUIDs, while the create order expects a list of objects.
        # This parameter makes that distinction possible.
        self._handle_action_updates(resolve_output_format="update_action")

        # The `update` method is now complete. The `self.resource` and `self.has_changed`
        # attributes have been correctly modified by the base class methods, and are
        # ready for the final `exit()` call in the main `run()` loop.

    def delete(self):
        """
        Terminates the resource by calling the marketplace termination endpoint.
        """
        if self.resource:
            # The API requires using the resource's specific 'marketplace_resource_uuid'
            # for termination actions.
            uuid_to_terminate = self.resource["marketplace_resource_uuid"]
            path = f"/api/marketplace-resources/{uuid_to_terminate}/terminate/"

            # Build the termination payload from configured attributes.
            termination_payload = {}
            attributes = {}
            term_attr_map = self.context.get("termination_attributes_map", {})

            for ansible_name, api_name in term_attr_map.items():
                if self.module.params.get(ansible_name) is not None:
                    attributes[api_name] = self.module.params[ansible_name]

            if attributes:
                termination_payload["attributes"] = attributes

            order, _ = self._send_request("POST", path, data=termination_payload)
            self.has_changed = True
            # After termination, the resource is considered gone.
            self.resource = None
            self.order = order

    def _wait_for_order(self, order_uuid):
        """
        Polls a marketplace order until it reaches a terminal state (done, erred, etc.).
        """
        timeout = self.module.params.get("timeout", 600)
        interval = self.module.params.get("interval", 20)
        start_time = time.time()

        while time.time() - start_time < timeout:
            order, _ = self._send_request(
                "GET", f"/api/marketplace-orders/{order_uuid}/"
            )

            if order and order["state"] == "done":
                # CRITICAL: After the order completes, the resource has been created.
                # We must re-fetch its final state to return accurate data to the user.
                self.resource = self.check_existence()
                return
            if order and order["state"] in ["erred", "rejected", "canceled"]:
                self.module.fail_json(
                    msg=f"Order finished with status '{order['state']}'. Error message: {order.get('error_message')}"
                )
                return

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
            for field in self.context["update_fields"]:
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
        self.module.exit_json(
            changed=self.has_changed, resource=self.resource, order=self.order
        )
