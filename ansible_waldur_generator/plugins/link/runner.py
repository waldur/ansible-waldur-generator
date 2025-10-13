from ansible_waldur_generator.interfaces.command import Command
from ansible_waldur_generator.interfaces.resolver import ParameterResolver
from ansible_waldur_generator.interfaces.runner import BaseRunner


class LinkRunner(BaseRunner):
    """Runner for modules that manage a link between two resources."""

    def __init__(self, module, context):
        super().__init__(module, context)
        self.resolver = ParameterResolver(self)
        self.source_object = None
        self.target_object = None
        self.is_linked = False

    def check_existence(self):
        """
        Custom existence check for a link. It resolves all context parameters
        first, then the source and target, and finally checks if the link exists.
        """
        # --- NEW: Dependency-aware resolution ---
        resolver_order = self.context.get("resolver_order", [])

        # 1. Resolve all parameters in the correct dependency order.
        # This populates the resolver's cache for subsequent lookups.
        for param_name in resolver_order:
            if (
                param_name in self.module.params
                and self.module.params[param_name] is not None
            ):
                self.resolver.resolve(param_name, self.module.params[param_name])

        # 2. Retrieve the fully resolved source and target objects from the cache.
        source_param = self.context["source"]["param"]
        target_param = self.context["target"]["param"]
        self.source_object = self.resolver.cache.get(source_param)
        self.target_object = self.resolver.cache.get(target_param)

        if not self.source_object:
            self.module.fail_json(
                msg=f"Source resource '{self.module.params[source_param]}' not found."
            )
        if not self.target_object:
            self.module.fail_json(
                msg=f"Target resource '{self.module.params[target_param]}' not found."
            )

        # 3. Check for the link using the target's URL.
        link_key = self.context["link_check_key"]
        current_link_url = self.source_object.get(link_key)
        target_object_url = self.target_object.get("url")

        self.is_linked = current_link_url == target_object_url

        # The 'resource' for the runner is the source object itself.
        self.resource = self.source_object

    def plan_creation(self) -> list:
        """Plan to create the link (e.g., attach)."""
        # The payload requires the target's URL.
        payload = {self.context["target"]["param"]: self.target_object["url"]}

        for param_name in self.context.get("link_param_names", []):
            if self.module.params.get(param_name) is not None:
                payload[param_name] = self.module.params[param_name]

        return [
            Command(
                self,
                method="POST",
                path=self.context["link_op_path"],
                command_type="action",
                path_params={"uuid": self.source_object["uuid"]},
                data=payload,
                description=f"Link {self.context['source']['resource_type']} to {self.context['target']['resource_type']}",
            )
        ]

    def plan_update(self) -> list:
        """Linking is binary; there is no 'update' state."""
        return []

    def plan_deletion(self) -> list:
        """Plan to remove the link (e.g., detach)."""
        return [
            Command(
                self,
                method="POST",
                path=self.context["unlink_op_path"],
                command_type="action",
                path_params={"uuid": self.source_object["uuid"]},
                description=f"Unlink {self.context['source']['resource_type']} from {self.context['target']['resource_type']}",
            )
        ]

    def run(self):
        """
        Overrides the standard run to use a custom existence check flag.
        """
        self.check_existence()

        state = self.module.params["state"]

        self.plan = []
        if self.is_linked:
            if state == "absent":
                self.plan = self.plan_deletion()
        elif state == "present":
            self.plan = self.plan_creation()

        if self.module.check_mode:
            self.handle_check_mode(self.plan)
            return

        self.execute_change_plan(self.plan)

        # Re-fetch the source object to return its final state
        # The runner.resource is updated by the command execution if needed,
        # but for link/unlink, we must re-check to get the fresh state.
        self.check_existence()

        self.exit(plan=self.plan)
