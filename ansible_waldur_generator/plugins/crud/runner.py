from ansible_waldur_generator.interfaces.resolver import ParameterResolver
from ansible_waldur_generator.interfaces.runner import BaseRunner

from ansible_waldur_generator.interfaces.command import Command


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
        return [
            Command(
                self,
                method="POST",
                path=self.context["create_path"],
                command_type="create",
                data=payload,
                path_params=path_params,
                description=f"Create new {self.context['resource_type']}",
            )
        ]

    def plan_update(self) -> list[Command]:
        """
        Builds the change plan for updating an existing resource.

        This method is called by `BaseRunner.run()` only when the resource already
        exists and the desired state is 'present'. It delegates the detailed
        planning for both simple and complex updates to the powerful helper
        methods inherited from the `BaseRunner`, promoting maximum code reuse.

        Returns:
            A list of `Command` objects, or an empty list if no updates are needed.
        """
        plan = []
        plan.extend(self._build_simple_update_command())
        plan.extend(self._build_action_update_commands())
        return plan

    def plan_deletion(self) -> list[Command]:
        """
        Builds the change plan for deleting an existing resource.

        This method is called by `BaseRunner.run()` only when the resource
        exists and the desired state is 'absent'.

        Returns:
            A list containing one `DeleteCommand` object.
        """
        # --- Step 1: Resolve Path Parameters for Simple or Nested Endpoints ---
        path_params = {}
        destroy_path_maps = self.context.get("path_param_maps", {}).get("destroy", {})

        if not destroy_path_maps:
            # Fallback to original simple logic for single-parameter paths.
            path_params = {"uuid": self.resource["uuid"]}
        else:
            # New, flexible logic for multi-parameter paths.
            for path_key, ansible_param_name in destroy_path_maps.items():
                # If the Ansible parameter is 'name', it refers to the primary resource itself.
                # Its value in the path should be the resource's UUID, which we found during the existence check.
                if ansible_param_name == "name":
                    path_params[path_key] = self.resource["uuid"]
                else:
                    # Otherwise, it's a parent/context resource that must be resolved.
                    parent_identifier = self.module.params.get(ansible_param_name)
                    if parent_identifier is None:
                        self.module.fail_json(
                            msg=f"Parameter '{ansible_param_name}' is required for deletion."
                        )

                    resolved_url = self.resolver.resolve_to_url(
                        ansible_param_name, parent_identifier
                    )
                    path_params[path_key] = resolved_url.strip("/").split("/")[-1]

        # --- Step 2: Return the Final Command ---
        return [
            Command(
                self,
                method="DELETE",
                path=self.context["destroy_path"],
                command_type="delete",
                path_params=path_params,
                description=f"Delete {self.context['resource_type']} '{self.resource.get('name', self.resource.get('uuid'))}'",
            )
        ]
