import time

from ansible.module_utils.basic import AnsibleModule
from waldur_api_client.models import OrderState

from ansible_waldur_generator.interfaces.runner import BaseRunner


class OrderRunner(BaseRunner):
    """
    A runner for modules that operate via the standard "resource-through-order" pattern.

    This logic encapsulates the following workflow:
    1.  Check for the existence of the final resource (e.g., an OpenStack volume).
    2.  If `state=present`:
        - If the resource exists, check if it needs to be updated.
        - If the resource does not exist, create a marketplace order,
          and optionally wait for its completion.
    3.  If `state=absent`:
        - If the resource exists, terminate it through the marketplace.
        - If the resource does not exist, do nothing.
    """

    def __init__(self, module: AnsibleModule, context: dict):
        """
        Initializes the base class and sets the initial state of the resource.
        """
        super().__init__(module, context)
        # `self.resource` will hold the found resource object or None.
        self.resource = None

    def run(self):
        """
        The main entry point that orchestrates the entire module lifecycle.
        """
        # 1. Determine if the resource currently exists in the system.
        self.check_existence()

        # 2. If the module is run in --check mode, we only predict changes.
        if self.module.check_mode:
            self.handle_check_mode()
            return  # Terminate execution

        # 3. Core logic based on the desired state and current existence.
        if self.resource:
            # The resource EXISTS.
            if self.module.params["state"] == "present":
                # Desired state: 'present'. Check if an update is needed.
                self.update()
            elif self.module.params["state"] == "absent":
                # Desired state: 'absent'. Delete the resource.
                self.delete()
        else:
            # The resource does NOT EXIST.
            if self.module.params["state"] == "present":
                # Desired state: 'present'. Create the resource.
                self.create()
            # If desired state is 'absent' and the resource is already gone, do nothing.

        # 4. Finalize the module's execution, returning the final state and the `changed` flag.
        self.exit()

    def check_existence(self):
        """
        Checks if a resource exists using the `existence_check_func` from the context.
        It searches by name (`name_exact`) and context (e.g., `project_uuid`).
        """
        try:
            # Start building the keyword arguments for the SDK function call.
            # Searching by exact name is the standard for checking existence.
            api_call_kwargs = {"name_exact": self.module.params["name"]}

            # Resolve context parameters (e.g., 'project') into UUIDs for filtering.
            # `existence_check_filter_keys` is a map of {'param_name': 'sdk_filter_key'}
            # Example: {'project': 'project_uuid'}
            filter_keys = self.context.get("existence_check_filter_keys", {})
            for param_name, filter_key in filter_keys.items():
                if self.module.params.get(param_name):
                    # Use the common helper to get the resource's URL by name or UUID.
                    resolved_url = self._resolve_to_url(
                        # The functions for resolution are taken from the resolvers context.
                        list_func=self.context["resolvers"][param_name]["list_func"],
                        retrieve_func=self.context["resolvers"][param_name][
                            "retrieve_func"
                        ],
                        value=self.module.params[param_name],
                        error_message=self.context["resolvers"][param_name][
                            "error_message"
                        ],
                    )
                    # Extract the UUID from the URL and add it to the filter arguments.
                    if resolved_url:
                        api_call_kwargs[filter_key] = resolved_url.split("/")[-2]

            # Call the SDK function passed from the Builder.
            check_func = self.context["existence_check_func"]
            resources = check_func.sync(client=self.client, **api_call_kwargs)

            if len(resources) > 1:
                self.module.warn(
                    f"Multiple resources found for '{self.module.params['name']}'. "
                    "The first one will be used. For uniqueness, please use UUID."
                )

            # Store the found resource, or None if nothing was found.
            self.resource = resources[0] if resources else None

        except Exception as e:
            self.module.fail_json(
                msg=f"Error checking for existence of resource "
                f"'{self.context['resource_type']}': {e}"
            )

    def create(self):
        """
        Creates a new resource by creating and submitting a marketplace order.
        """
        try:
            # 1. Resolve all necessary parameters for the order (project, offering, etc.) into URLs.
            resolved_urls = {}
            for name, resolver in self.context["resolvers"].items():
                if self.module.params.get(name):
                    resolved_urls[name] = self._resolve_to_url(
                        list_func=resolver["list_func"],
                        retrieve_func=resolver["retrieve_func"],
                        value=self.module.params[name],
                        error_message=resolver["error_message"],
                    )

            # 2. Build the nested `attributes` dictionary for the order payload.
            attributes = {"name": self.module.params["name"]}
            for key in self.context["attribute_param_names"]:
                if key in self.module.params and self.module.params[key] is not None:
                    # If the parameter is resolvable, use its resolved URL.
                    if key in resolved_urls:
                        attributes[key] = resolved_urls[key]
                    else:
                        attributes[key] = self.module.params[key]

            # 3. Create the request body using the model and URLs from the context/resolved parameters.
            order_request_body = self.context["order_model_class"](
                project=resolved_urls["project"],
                offering=resolved_urls["offering"],
                attributes=attributes,
                # By default, accept the terms of service.
                accepting_terms_of_service=True,
            )

            # 4. Call the SDK function to create the order.
            order = self.context["order_create_func"].sync(
                client=self.client, body=order_request_body
            )

            # 5. If required, wait for the order to complete.
            if self.module.params.get("wait", True):
                self._wait_for_order(order.uuid)

            # Mark that the system state has changed.
            self.has_changed = True

        except Exception as e:
            self.module.fail_json(msg=f"Error creating resource: {e}")

    def update(self):
        """
        Updates an existing resource if any of the tracked parameters have changed.
        """
        # If no update function is defined in the configuration, exit.
        if not self.context.get("update_func"):
            return

        try:
            update_payload = {}
            # Compare values in the module params with values in the existing resource.
            for field in self.context["update_check_fields"]:
                param_value = self.module.params.get(field)
                resource_value = getattr(self.resource, field, None)
                if param_value is not None and param_value != resource_value:
                    update_payload[field] = param_value

            # If there is anything to update, send the request.
            if update_payload:
                # `update_model_class` is the request model for the update (e.g., OpenStackVolumeRequest).
                update_request_body = self.context["update_model_class"](
                    **update_payload
                )

                # Call the SDK function to perform the update.
                updated_resource = self.context["update_func"].sync(
                    client=self.client,
                    uuid=self.resource.uuid,
                    body=update_request_body,
                )

                self.resource = updated_resource
                self.has_changed = True

        except Exception as e:
            self.module.fail_json(msg=f"Error updating resource: {e}")

    def delete(self):
        """
        Terminates the resource via the marketplace endpoint.
        """
        try:
            # Get the resource UUID for termination. The field name (`marketplace_resource_uuid`)
            # is hardcoded in the plugin as it is a standard.
            uuid_to_terminate = getattr(self.resource, "marketplace_resource_uuid")

            # Call the SDK function to terminate the resource.
            # The `terminate_model_class` is usually empty (ResourceTerminateRequest).
            self.context["terminate_func"].sync(
                client=self.client,
                uuid=uuid_to_terminate,
                body=self.context["terminate_model_class"](),
            )

            self.has_changed = True
            # After deletion, the resource no longer exists.
            self.resource = None

        except Exception as e:
            self.module.fail_json(msg=f"Error deleting resource: {e}")

    def _wait_for_order(self, order_uuid: str):
        """
        A helper method to wait for an order to complete.
        It periodically polls the order's status until it becomes final.
        """
        timeout = self.module.params.get("timeout", 600)
        interval = self.module.params.get("interval", 20)
        waited = 0

        while waited < timeout:
            order = self.context["order_poll_func"].sync(
                client=self.client, uuid=order_uuid
            )

            if order.state == OrderState.DONE:
                # The order completed successfully.
                return
            if order.state in [
                OrderState.ERRED,
                OrderState.REJECTED,
                OrderState.CANCELED,
            ]:
                # The order failed.
                raise Exception(
                    f"Order finished with status '{order.state.value}'. "
                    f"Error message: {order.error_message}"
                )

            # If the order is still processing, wait and try again.
            time.sleep(interval)
            waited += interval

        # If we exit the loop due to a timeout.
        raise TimeoutError(f"Timeout waiting for order {order_uuid} to complete.")

    def handle_check_mode(self):
        """
        Predicts changes for --check mode without actually executing them.
        """
        state = self.module.params["state"]
        if state == "present" and not self.resource:
            # If the resource is absent but should be present, a change (create) will occur.
            self.has_changed = True
        elif state == "absent" and self.resource:
            # If the resource is present but should be absent, a change (delete) will occur.
            self.has_changed = True
        elif state == "present" and self.resource and self.context.get("update_func"):
            # Check if an update would occur.
            for field in self.context["update_check_fields"]:
                param_value = self.module.params.get(field)
                resource_value = getattr(self.resource, field, None)
                if param_value is not None and param_value != resource_value:
                    self.has_changed = True
                    break  # One change is enough to set the flag
        self.exit()

    def exit(self):
        """
        Formats the final response and exits the module.
        """
        # Convert the resource object to a dictionary if it exists.
        resource_dict = self.resource.to_dict() if self.resource else None
        self.module.exit_json(changed=self.has_changed, resource=resource_dict)
