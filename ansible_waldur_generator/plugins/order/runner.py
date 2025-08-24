import time

from ansible_waldur_generator.interfaces.resolver import ParameterResolver
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
        data = self._send_request(
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
                attributes[key] = self.resolver.resolve(key, self.module.params[key])

        order_payload = {
            "project": project_url,
            "offering": offering_url,
            "attributes": attributes,
            "accepting_terms_of_service": True,
        }
        plan = self.module.params.get("plan")
        if plan:
            order_payload.update({"plan": plan})
        limits = self.module.params.get("limits")
        if limits:
            order_payload.update({"limits": limits})

        # Send the request to create the order.
        order = self._send_request(
            "POST", "/api/marketplace-orders/", data=order_payload
        )

        # If waiting is enabled, poll the order's status until completion.
        if self.module.params.get("wait", True) and order:
            self._wait_for_order(order["uuid"])
        self.order = order

        self.has_changed = True

    def update(self):
        """
        Updates an existing resource if its configuration has changed. This method
        only handles simple, direct attribute updates (e.g., via PATCH).
        """
        # Do nothing if no update endpoint is configured for this resource.
        if not self.context.get("update_url"):
            return

        # --- Dependency Cache Priming ---
        # Instead of manually fetching dependencies, we now use a dedicated method on the
        # resolver to "prime" its cache. It fetches the full objects for the resource's
        # 'offering' and 'project' from their URLs, making them available for filtering.
        if self.resource:
            self.resolver.prime_cache_from_resource(
                self.resource, ["offering", "project"]
            )

        # If the user provides an 'offering' or 'project' parameter, their choice
        # should override the existing one. We explicitly resolve it here to
        # update the cache with the user-provided value.
        if self.module.params.get("offering"):
            self.resolver.resolve("offering", self.module.params["offering"])
        if self.module.params.get("project"):
            self.resolver.resolve("project", self.module.params["project"])

        # Use a flag to perform the re-fetch only once at the end.
        needs_refetch = False

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
                # The idempotency check must compare like with like.
                # We use the resolver to get the fully resolved, API-ready version
                # of the user's input *before*
                # comparing them to the current state of the resource.
                resolved_payload_for_comparison = self.resolver.resolve(
                    param_name, param_value
                )

                if resolved_payload_for_comparison != self.resource.get(compare_key):
                    # The payload for the API must be wrapped in a dictionary
                    final_api_payload = {param_name: resolved_payload_for_comparison}
                    self._send_request(
                        "POST",
                        action_info["path"],
                        data=final_api_payload,
                        path_params={"uuid": self.resource["uuid"]},
                    )
                    self.has_changed = True
                    needs_refetch = True

        # After all actions are processed, re-fetch the state if necessary.
        if needs_refetch:
            self.resource = self.check_existence()

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
        self.module.exit_json(
            changed=self.has_changed, resource=self.resource, order=self.order
        )
