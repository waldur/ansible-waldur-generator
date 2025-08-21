import time

from ansible_waldur_generator.interfaces.runner import BaseRunner


class OrderRunner(BaseRunner):
    """
    A runner for modules that operate via the standard "resource-through-order" pattern.
    """

    def __init__(self, module, context):
        """
        Initializes the base class and sets the initial state of the resource.
        """
        super().__init__(module, context)
        self.resource = None

    def run(self):
        """
        The main entry point that orchestrates the entire module lifecycle.
        """
        self.check_existence()
        if self.module.check_mode:
            self.handle_check_mode()
            return
        if self.resource:
            if self.module.params["state"] == "present":
                self.update()
            elif self.module.params["state"] == "absent":
                self.delete()
        else:
            if self.module.params["state"] == "present":
                self.create()
        self.exit()

    def check_existence(self):
        """
        Checks if a resource exists.
        """
        params = {"name_exact": self.module.params["name"]}
        filter_keys = self.context.get("existence_check_filter_keys", {})
        for param_name, filter_key in filter_keys.items():
            if self.module.params.get(param_name):
                resolved_url = self._resolve_to_url(
                    path=self.context["resolvers"][param_name]["url"],
                    value=self.module.params[param_name],
                    error_message=self.context["resolvers"][param_name][
                        "error_message"
                    ],
                )
                if resolved_url:
                    params[filter_key] = resolved_url.split("/")[-2]

        data = self._send_request(
            "GET",
            self.context["existence_check_url"],
            query_params=params,
        )
        if data and len(data) > 1:
            self.module.warn(
                f"Multiple resources found for '{self.module.params['name']}'. The first one will be used."
            )
        self.resource = data[0] if data else None

    def create(self):
        """
        Creates a new resource by creating and submitting a marketplace order.
        """
        resolved_urls = self._resolve_all_parameters()

        attributes = {"name": self.module.params["name"]}
        for key in self.context["attribute_param_names"]:
            if key in self.module.params and self.module.params[key] is not None:
                # Use the pre-resolved URL if available
                attributes[key] = resolved_urls.get(key, self.module.params[key])

        order = self._send_request(
            "POST",
            "/api/marketplace-orders/",
            data={
                "project": resolved_urls["project"],
                "offering": resolved_urls["offering"],
                "plan": self.module.params.get("plan"),
                "limits": self.module.params.get("limits", {}),
                "attributes": attributes,
                "accepting_terms_of_service": True,
            },
        )

        if self.module.params.get("wait", True) and order:
            self._wait_for_order(order["uuid"])
        self.has_changed = True

    def update(self):
        """
        Updates an existing resource if any of the tracked parameters have changed.
        """
        if not self.context.get("update_url"):
            return

        update_payload = {}
        for field in self.context["update_check_fields"]:
            param_value = self.module.params.get(field)
            if self.resource:
                resource_value = self.resource.get(field)
                if param_value is not None and param_value != resource_value:
                    update_payload[field] = param_value

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
        Terminates the resource via the marketplace endpoint.
        """
        if self.resource:
            uuid_to_terminate = self.resource["marketplace_resource_uuid"]
            path = f"/api/marketplace-resources/{uuid_to_terminate}/terminate/"
            self._send_request("POST", path, data={})
            self.has_changed = True
            self.resource = None

    def _wait_for_order(self, order_uuid):
        """
        A helper method to wait for an order to complete.
        """
        timeout = self.module.params.get("timeout", 600)
        interval = self.module.params.get("interval", 20)
        waited = 0

        while waited < timeout:
            order = self._send_request(
                "GET",
                f"/api/marketplace-orders/{order_uuid}/",
            )

            if order and order["state"] == "done":
                return
            if order and order["state"] in ["erred", "rejected", "canceled"]:
                self.module.fail_json(
                    msg=f"Order finished with status '{order['state']}'. Error message: {order.get('error_message')}"
                )

            time.sleep(interval)
            waited += interval

        self.module.fail_json(
            msg=f"Timeout waiting for order {order_uuid} to complete."
        )

    def handle_check_mode(self):
        """
        Predicts changes for --check mode without actually executing them.
        """
        state = self.module.params["state"]
        if state == "present" and not self.resource:
            self.has_changed = True
        elif state == "absent" and self.resource:
            self.has_changed = True
        elif state == "present" and self.resource and self.context.get("update_url"):
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
        Formats the final response and exits the module.
        """
        self.module.exit_json(changed=self.has_changed, resource=self.resource)

    def _resolve_all_parameters(self):
        """
        Resolves all required parameters in an order that respects dependencies
        defined in the 'filter_by' configuration.

        Returns a dictionary of resolved URLs.
        """
        resolved_data = {}  # Stores the full API response for each resolved param
        resolved_urls = {}
        params_to_resolve = list(self.context["resolvers"].keys())

        # Use a simple multi-pass approach to resolve dependencies.
        # This handles one level of dependency, which is sufficient for this use case.
        for pass_num in range(2):
            remaining_params = []
            for name in params_to_resolve:
                if self.module.params.get(name) is None:
                    continue

                resolver_conf = self.context["resolvers"][name]
                dependencies = resolver_conf.get("filter_by", [])

                # In Pass 1 (pass_num=0), resolve params with NO dependencies.
                # In Pass 2 (pass_num=1), resolve params WITH dependencies.
                if (pass_num == 0 and dependencies) or (
                    pass_num == 1 and not dependencies
                ):
                    remaining_params.append(name)
                    continue

                query_params = {}
                # Build query params from dependencies if they exist
                for dep in dependencies:
                    source_param = dep["source_param"]
                    if source_param not in resolved_data:
                        self.module.fail_json(
                            msg=f"Configuration error: Resolver for '{name}' depends on '{source_param}', which has not been resolved yet."
                        )

                    source_value = resolved_data[source_param].get(dep["source_key"])
                    if source_value is None:
                        self.module.fail_json(
                            msg=f"Could not find key '{dep['source_key']}' in the response for '{source_param}'."
                        )

                    query_params[dep["target_key"]] = source_value

                # Now, perform the actual resolution for this parameter
                resource_list = self._resolve_to_list(
                    path=resolver_conf["url"],
                    value=self.module.params[name],
                    query_params=query_params,
                )

                if not resource_list:
                    self.module.fail_json(
                        msg=resolver_conf["error_message"].format(
                            value=self.module.params[name]
                        )
                    )

                if len(resource_list) > 1:
                    self.module.warn(
                        f"Multiple resources found for '{self.module.params[name]}'. Using the first one."
                    )

                resolved_data[name] = resource_list[0]
                resolved_urls[name] = resource_list[0]["url"]

            params_to_resolve = remaining_params

        return resolved_urls

    def _resolve_to_list(self, path, value, query_params=None):
        """A helper to resolve a name/UUID to a list of matching resources."""
        if self._is_uuid(value):
            # If it's a UUID, we can fetch it directly and wrap it in a list.
            # We ignore query_params here as direct fetch is more specific.
            resource = self._send_request("GET", f"{path}{value}/")
            return [resource] if resource else []

        # It's a name, so we add it to the query and send.
        final_query = query_params.copy() if query_params else {}
        final_query["name"] = value
        return self._send_request("GET", path, query_params=final_query)
