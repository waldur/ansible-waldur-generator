from ansible_waldur_generator.interfaces.resolver import ParameterResolver
from ansible_waldur_generator.interfaces.runner import BaseRunner


class CrudRunner(BaseRunner):
    """
    Handles the core execution logic for a standard CRUD-based Ansible module.
    It is designed to be stateless and configurable via a `context` dictionary
    provided during initialization.

    This runner supports both simple and complex CRUD patterns:
    - Simple: Create, Read, Delete operations on a top-level API endpoint.
    - Complex:
        - Creation on a nested endpoint (e.g., `/api/parents/{uuid}/children/`).
        - A multi-faceted update process for existing resources, which can
          handle both simple field changes (PATCH) and special actions (POST)
          within a single `state: present` task.
    """

    def __init__(self, module, context):
        """
        Initializes the runner and its composed ParameterResolver.
        """
        super().__init__(module, context)
        # An instance of the resolver is created, giving this runner access to
        # all the centralized resolution logic.
        self.resolver = ParameterResolver(self)

    def run(self):
        """
        The main execution entrypoint for the runner. It orchestrates the entire
        module lifecycle based on the desired state and whether the resource
        currently exists.
        """
        # Step 1: Determine the current state of the resource.
        self.check_existence()

        # Step 2: If in check mode, predict changes without making them.
        if self.module.check_mode:
            self.handle_check_mode()
            return

        # Step 3: Execute actions based on current state and desired state.
        if self.resource:
            # The resource exists.
            if self.module.params["state"] == "present":
                # User wants it to exist, so we check for and apply updates.
                self.update()
            elif self.module.params["state"] == "absent":
                # User wants it gone, so we delete it.
                self.delete()
        else:
            # The resource does not exist.
            if self.module.params["state"] == "present":
                # User wants it to exist, so we create it.
                self.create()

        # Step 4: Exit the module with the final state.
        self.exit()

    def check_existence(self):
        """
        Checks if the resource exists by querying the configured `list_path` API
        endpoint with an exact name match.
        """
        params = {"name_exact": self.module.params["name"]}
        data, _ = self._send_request(
            "GET", self.context["list_path"], query_params=params
        )
        # The API returns a list; we take the first result if it exists.
        self.resource = data[0] if data else None

    def create(self):
        """
        Creates a new resource by sending a POST request to the configured `create_path`.
        It handles both top-level and nested creation endpoints.
        """
        # 1. Assemble the request payload from the relevant Ansible parameters.
        payload = {
            key: self.module.params[key]
            for key in self.context["model_param_names"]
            if key in self.module.params and self.module.params[key] is not None
        }
        for name in self.context.get("resolvers", {}).keys():
            if self.module.params.get(name) and name in payload:
                payload[name] = self.resolver.resolve_to_url(
                    name, self.module.params[name]
                )

        # 2. Prepare the API path and any required path parameters for nested endpoints.
        path = self.context["create_path"]
        path_params = {}

        # Check if the create path is nested (e.g., '/api/tenants/{uuid}/security_groups/')
        create_path_maps = self.context.get("path_param_maps", {}).get("create", {})
        for path_param_key, ansible_param_name in create_path_maps.items():
            ansible_param_value = self.module.params.get(ansible_param_name)
            if not ansible_param_value:
                self.module.fail_json(
                    msg=f"Parameter '{ansible_param_name}' is required for creation."
                )

            # Resolve the parent resource's name/UUID to its UUID for the path.
            resolved_url = self.resolver.resolve_to_url(
                ansible_param_name, ansible_param_value
            )

            # Extract the UUID from the resolved URL.
            path_params[path_param_key] = resolved_url.strip("/").split("/")[-1]

        # 3. Send the request and store the newly created resource.
        self.resource, _ = self._send_request(
            "POST", path, data=payload, path_params=path_params
        )
        self.has_changed = True

    def update(self):
        """
        Updates an existing resource if its configuration has changed. This method
        intelligently handles both simple field updates and complex action-based updates.
        """
        if not self.resource:
            return

        # 1. Handle simple field updates (e.g., name, description).
        update_path = self.context.get("update_path")
        update_fields = self.context.get("update_fields", [])
        if update_path and update_fields:
            update_payload = {}
            for field in update_fields:
                param_value = self.module.params.get(field)
                # Check if the user-provided value is different from the existing resource's value.
                if param_value is not None and param_value != self.resource.get(field):
                    update_payload[field] = param_value
            # If there are changes, send a PATCH request.
            if update_payload:
                updated_resource, _ = self._send_request(
                    "PATCH",
                    update_path,
                    data=update_payload,
                    path_params={"uuid": self.resource["uuid"]},
                )
                # Merge the update response back into our local resource state.
                self.resource.update(updated_resource)
                self.has_changed = True

        # 2. Handle action-based updates (e.g., setting security group rules).
        update_actions = self.context.get("update_actions", {})
        for _, action_info in update_actions.items():
            param_name = action_info["param"]
            param_value = self.module.params.get(param_name)

            # Perform idempotency check before executing the action.
            # Compare the user-provided value with the corresponding field on the resource.
            check_field = action_info["check_field"]
            if param_value is not None and param_value != self.resource.get(
                check_field
            ):
                # Construct the request body based on the schema analysis
                # done by the plugin.
                if action_info.get("wrap_in_object"):
                    data_to_send = {param_name: param_value}
                else:
                    data_to_send = param_value

                _, status_code = self._send_request(
                    "POST",
                    action_info["path"],
                    data=data_to_send,
                    path_params={"uuid": self.resource["uuid"]},
                )

                # If the API accepted the task for async processing, wait for it.
                if status_code == 202 and self.module.params.get("wait", True):
                    self._wait_for_resource_state(self.resource["uuid"])
                else:
                    # For synchronous actions (200, 201, 204), re-fetch immediately.
                    self.check_existence()

                self.has_changed = True

    def delete(self):
        """
        Deletes the resource by sending a DELETE request to its endpoint.
        """
        if self.resource:
            path = self.context["destroy_path"]
            self._send_request(
                "DELETE", path, path_params={"uuid": self.resource["uuid"]}
            )
            self.has_changed = True
            self.resource = None  # The resource is now gone.

    def handle_check_mode(self):
        """
        Predicts changes for Ansible's --check mode without making any API calls.
        """
        state = self.module.params["state"]
        if state == "present" and not self.resource:
            self.has_changed = True  # Predicts creation.
        elif state == "absent" and self.resource:
            self.has_changed = True  # Predicts deletion.
        elif state == "present" and self.resource:
            # Predicts simple field updates.
            for field in self.context.get("update_fields", []):
                param_value = self.module.params.get(field)
                if param_value is not None and param_value != self.resource.get(field):
                    self.has_changed = True
                    break
            # Predicts action-based updates.
            if not self.has_changed:
                for action_info in self.context.get("update_actions", {}).values():
                    param_value = self.module.params.get(action_info["param"])
                    # Add idempotency check for actions in check mode.
                    check_field = action_info["check_field"]
                    if param_value is not None and param_value != self.resource.get(
                        check_field
                    ):
                        self.has_changed = True
                        break

        self.exit()

    def exit(self):
        """
        Formats the final response and exits the module execution.
        """
        self.module.exit_json(changed=self.has_changed, resource=self.resource)
