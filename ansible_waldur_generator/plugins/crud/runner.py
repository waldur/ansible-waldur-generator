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
        Orchestrates the update process for an existing resource when `state: present`.

        This method's primary role is to ensure that an existing resource's configuration
        matches the state desired by the user in the Ansible playbook. It handles both
        simple field updates (e.g., changing a 'description') and complex, action-based
        updates (e.g., setting firewall rules for a security group).

        By leveraging the powerful, generic handler methods inherited from `BaseRunner`,
        this implementation is clean, concise, and follows a clear, logical flow:
        1.  First, it handles any simple, direct attribute changes via `PATCH`.
        2.  Second, it processes any complex, idempotent actions via `POST`.

        This separation ensures that simple updates are processed efficiently, while
        complex updates benefit from the robust "resolve -> normalize -> compare -> execute"
        workflow provided by the base class. The `CrudRunner` itself doesn't need to
        contain any complex update logic; it simply delegates to the shared toolkit.
        """
        # --- Guard Clause: Ensure a Resource Exists ---
        # The update method is only meaningful if a resource was found during the
        # initial `check_existence()` call. If `self.resource` is `None`, it means
        # the resource doesn't exist, and the `create()` method will be called
        # by the main `run()` logic instead. We can safely exit here.
        if not self.resource:
            return

        # --- Step 1: Handle Simple Field Updates ---
        # Delegate the entire process of handling simple updates to the `_handle_simple_updates`
        # method inherited from `BaseRunner`. This shared method will:
        #   - Compare all fields listed in `context['update_fields']`.
        #   - Build a `PATCH` payload with only the changed values.
        #   - Send the request if and only if changes are detected.
        #   - Update `self.resource` and `self.has_changed` accordingly.
        # This keeps the `CrudRunner` clean and free of duplicated logic.
        self._handle_simple_updates()

        # --- Step 2: Handle Complex, Action-Based Updates ---
        # After handling simple updates, we delegate to the `_handle_action_updates`
        # method, also inherited from `BaseRunner`. This powerful, generic engine will:
        #   - Iterate through all actions defined in `context['update_actions']`.
        #   - For each action, it will:
        #       a) Resolve the user-provided parameters (e.g., converting a subnet
        #          name into a full API URL).
        #       b) Perform a robust, order-insensitive idempotency check using the
        #          `_normalize_for_comparison` utility.
        #       c) Execute a `POST` request to the action's endpoint only if a change
        #          is needed.
        #       d) Handle any asynchronous (HTTP 202) responses by waiting.
        #       e) Re-fetch the resource state at the end if necessary.
        #
        # For the `CrudRunner`, no special setup is required before calling this method.
        # We use the default `resolve_output_format` because CRUD modules typically
        # don't have the dual-context complexity of `OrderRunner`.
        self._handle_action_updates()

        # The `update` method is now complete. The `self.resource` and `self.has_changed`
        # attributes have been correctly modified by the base class methods, and are
        # ready for the final `exit()` call in the main `run()` loop.

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
