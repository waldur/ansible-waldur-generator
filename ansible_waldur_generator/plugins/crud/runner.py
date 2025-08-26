from ansible_waldur_generator.interfaces.resolver import ParameterResolver
from ansible_waldur_generator.interfaces.runner import BaseRunner

from ansible_waldur_generator.interfaces.command import CreateCommand, DeleteCommand


class CrudRunner(BaseRunner):
    """
    A declarative runner for standard Create, Read, Update, Delete (CRUD) modules.

    This class is a concrete implementation of the `BaseRunner` and its primary
    responsibility is to translate the user's desired state into a "change plan".
    It achieves this by implementing the three abstract planning methods:
    `plan_creation`, `plan_update`, and `plan_deletion`.

    It does not contain any complex workflow logic (like `if/elif/else` blocks for
    state). All of that orchestration is handled by the universal `run()` method
    in the `BaseRunner`, making this implementation highly focused and readable.
    """

    def __init__(self, module, context):
        """
        Initializes the CrudRunner.

        Args:
            module: The AnsibleModule instance, providing access to parameters.
            context: The pre-processed configuration dictionary from the generator.
        """
        super().__init__(module, context)
        # Instantiate the resolver, giving this runner access to all centralized
        # logic for converting user-friendly names/UUIDs into API-ready URLs.
        self.resolver = ParameterResolver(self)

    def plan_creation(self) -> list:
        """
        Builds the change plan for creating a new resource.

        This method is called by the `BaseRunner.run()` orchestrator only when
        the resource does not currently exist and the desired state is 'present'.
        It assembles the necessary API payload, resolves any foreign keys or
        nested path parameters, and returns a list containing a single, fully
        configured `CreateCommand`.

        Returns:
            A list containing one `CreateCommand` object.
        """
        # --- Step 1: Assemble the Request Body Payload ---

        # Gather all parameters that are part of the resource's data model,
        # but only if the user has provided a non-None value for them. This
        # prevents sending empty keys to the API.
        payload = {
            key: self.module.params[key]
            for key in self.context["model_param_names"]
            if key in self.module.params and self.module.params[key] is not None
        }

        # Resolve any foreign keys within the payload. For each parameter that has
        # a configured resolver, convert its user-provided name/UUID into the
        # full API URL that the backend expects.
        for name in self.context.get("resolvers", {}).keys():
            if self.module.params.get(name) and name in payload:
                payload[name] = self.resolver.resolve_to_url(
                    name, self.module.params[name]
                )

        # --- Step 2: Resolve Path Parameters for Nested Endpoints ---

        # This handles the critical edge case where a resource is created under a parent,
        # e.g., POST /api/tenants/{uuid}/security_groups/.
        path_params = {}
        create_path_maps = self.context.get("path_param_maps", {}).get("create", {})
        for path_param_key, ansible_param_name in create_path_maps.items():
            parent_identifier = self.module.params.get(ansible_param_name)

            # Defensive check: The parent identifier must be provided for nested creation.
            if not parent_identifier:
                self.module.fail_json(
                    msg=f"Parameter '{ansible_param_name}' is required for creation, as it defines the parent resource."
                )

            # Resolve the parent's name/UUID to its full URL.
            resolved_url = self.resolver.resolve_to_url(
                ansible_param_name, parent_identifier
            )
            # Extract the UUID from the URL to be used as the path parameter.
            path_params[path_param_key] = resolved_url.strip("/").split("/")[-1]

        # --- Step 3: Return the Final Command ---
        # Instantiate and return the `CreateCommand` encapsulated in a list.
        return [CreateCommand(self, self.context["create_path"], payload, path_params)]

    def plan_update(self) -> list:
        """
        Builds the change plan for updating an existing resource.

        This method is called by `BaseRunner.run()` only when the resource already
        exists and the desired state is 'present'. It delegates the detailed
        planning for both simple and complex updates to the powerful helper
        methods inherited from the `BaseRunner`, promoting maximum code reuse.

        Returns:
            A list of `UpdateCommand` and/or `ActionCommand` objects, or an empty
            list if no updates are needed.
        """
        plan = []

        # Delegate planning for simple, direct attribute updates (PATCH requests).
        # This helper will return an `UpdateCommand` if any changes are detected.
        plan.extend(self._build_simple_update_command())

        # Delegate planning for complex, action-based updates (POST requests).
        # This helper will return a list of `ActionCommands` for any actions that
        # need to be executed.
        plan.extend(self._build_action_update_commands())

        return plan

    def plan_deletion(self) -> list:
        """
        Builds the change plan for deleting an existing resource.

        This method is called by `BaseRunner.run()` only when the resource
        exists and the desired state is 'absent'.

        Returns:
            A list containing one `DeleteCommand` object.
        """
        # The plan is simple: a single command to delete the resource by its UUID.
        # We pass the current `self.resource` object to the command so it can be
        # used to generate an accurate "before" state in the diff.
        return [
            DeleteCommand(
                self,
                self.context["destroy_path"],
                self.resource,
                path_params={"uuid": self.resource["uuid"]},
            )
        ]

    def exit(self, plan: list | None = None, diff: list | None = None):
        """
        Formats the final response for Ansible and exits the module.

        This method overrides the base implementation to provide a consistent
        exit signature for CRUD modules, which do not have an 'order' object.

        Args:
            plan (list, optional): The original plan, used to generate a diff if not in check mode.
            diff (list, optional): A pre-generated diff from check mode.
        """
        if diff is None:
            diff = [cmd.to_diff() for cmd in plan] if plan else []

        self.module.exit_json(
            changed=self.has_changed, resource=self.resource, diff=diff
        )
