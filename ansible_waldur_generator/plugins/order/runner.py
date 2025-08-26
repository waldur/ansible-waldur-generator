from ansible_waldur_generator.interfaces.resolver import ParameterResolver
from ansible_waldur_generator.interfaces.runner import BaseRunner
from ansible_waldur_generator.interfaces.command import (
    DeleteCommand,
    MarketplaceOrderCommand,
)

# A map of transformation functions, allowing the generator to configure
# data conversions (e.g., from user-friendly GiB to API-required MiB).
TRANSFORMATION_MAP = {
    "gb_to_mb": lambda x: int(x) * 1024,
}


class OrderRunner(BaseRunner):
    """
    Handles the execution logic for Ansible modules that manage resources via
    Waldur's asynchronous marketplace order workflow.

    This runner is a hybrid:
    - For **updates and deletions**, it uses the standard, robust "plan-and-execute"
      workflow inherited from `BaseRunner`, leveraging the Command pattern for
      clean, predictive changes.
    - For **creation**, it implements a specialized, direct-execution workflow to
      handle the unique, multi-step process of submitting and polling a marketplace order.

    This design provides the best of both worlds: the structured power of the
    Command pattern for standard operations, and the necessary flexibility for the
    asynchronous creation process.
    """

    def __init__(self, module, context):
        """
        Initializes the runner, its resolver, and determines the initial
        state of the resource.
        """
        super().__init__(module, context)
        # This will store the marketplace order object after a successful creation.
        self.order = None
        # Instantiate the powerful, centralized resolver for handling all
        # parameter-to-URL conversions.
        self.resolver = ParameterResolver(self)

    def plan_creation(self) -> list:
        """
        Handles the unique workflow for creating a resource via a marketplace order.

        Unlike simple CRUD, marketplace creation is an asynchronous, multi-step
        process that doesn't map cleanly to a single, atomic command. Therefore,
        this method deviates from the standard Command pattern for creation:

        - In **check mode**, it simply sets the `changed` flag and returns,
          signaling that a change is predicted.
        - In **execution mode**, it performs the entire create-and-wait logic
          directly and then returns an empty plan.

        This approach keeps the complex, special-case logic encapsulated here,
        while allowing updates and deletes to use the standard, elegant Command pattern.

        Returns:
            An empty list. The `run()` orchestrator interprets this as "execution for
            this phase is complete".
        """
        # If in check mode, we don't execute anything. We just predict that a
        # change will occur and let the `exit` method handle the diff.
        if self.module.check_mode:
            self.has_changed = True
            return []  # Return an empty plan.

        project_url = self.resolver.resolve("project", self.module.params["project"])
        offering_url = self.resolver.resolve("offering", self.module.params["offering"])

        attributes = {"name": self.module.params["name"]}
        for key in self.context["attribute_param_names"]:
            if key in self.module.params and self.module.params[key] is not None:
                attributes[key] = self.resolver.resolve(
                    key, self.module.params[key], output_format="create"
                )

        transformed_attributes = self._apply_transformations(attributes)

        # --- 2. Assemble and submit the order ---
        order_payload = {
            "project": project_url,
            "offering": offering_url,
            "attributes": transformed_attributes,
            "accepting_terms_of_service": True,
        }
        if self.module.params.get("plan"):
            order_payload["plan"] = self.module.params["plan"]
        if self.module.params.get("limits"):
            order_payload["limits"] = self.module.params["limits"]

        return [MarketplaceOrderCommand(self, order_payload)]

    def plan_update(self) -> list:
        """
        Builds the change plan for updating an existing marketplace resource.

        This method is the key to handling complex, context-dependent updates.
        Its primary responsibility is to perform the specialized setup required
        for marketplace resources *before* delegating the actual planning to the
        generic, powerful helpers in the `BaseRunner`.

        Returns:
            A list of `UpdateCommand` and/or `ActionCommand` objects.
        """
        # --- Step 1: Specialized Context Setup ---
        # Proactively prime the resolver's cache with the resource's key dependencies
        # (its `offering` and `project`). This is critical because resolving new
        # nested parameters (like a `subnet` name) requires knowing which tenant
        # to search in, a detail that comes from the offering's scope.
        self.resolver.prime_cache_from_resource(self.resource, ["offering", "project"])

        # Allow the user to override the primed context. If they provide a new
        # 'offering' parameter, we resolve it immediately. This overwrites the cached
        # offering from the existing resource, ensuring that all subsequent
        # resolutions are performed within the correct new scope.
        if self.module.params.get("offering"):
            self.resolver.resolve("offering", self.module.params["offering"])

        # --- Step 2: Delegate Planning to Base Class Helpers ---
        # With the context now correctly prepared, we delegate the detailed planning.
        plan = []
        plan.extend(self._build_simple_update_command())
        # We provide a crucial hint, `resolve_output_format="update_action"`, to ensure
        # parameters are formatted correctly for direct update endpoints, which may
        # differ from the format required by the 'create order' endpoint.
        plan.extend(
            self._build_action_update_commands(resolve_output_format="update_action")
        )

        return plan

    def plan_deletion(self) -> list:
        """
        Builds the change plan for terminating an existing marketplace resource.

        Returns:
            A list containing one `DeleteCommand` configured for POST-based termination.
        """
        # Marketplace resources are terminated via a POST to a specific action endpoint,
        # using their unique `marketplace_resource_uuid`.
        uuid_to_terminate = self.resource["marketplace_resource_uuid"]
        path = f"/api/marketplace-resources/{uuid_to_terminate}/terminate/"

        # Assemble the payload for termination, which can include special attributes
        # like 'force_destroy' or 'delete_volumes'.
        termination_payload = {}
        attributes = {}
        term_attr_map = self.context.get("termination_attributes_map", {})
        for ansible_name, api_name in term_attr_map.items():
            if self.module.params.get(ansible_name) is not None:
                attributes[api_name] = self.module.params[ansible_name]
        if attributes:
            termination_payload["attributes"] = attributes

        # Instantiate the `DeleteCommand`, explicitly setting the method to 'POST'.
        # This is the key to ensuring the correct API call is made.
        return [
            DeleteCommand(
                self, path, self.resource, data=termination_payload, method="POST"
            )
        ]

    def _apply_transformations(self, payload: dict) -> dict:
        """
        Applies configured value transformations to a payload dictionary.
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
                        pass
        return transformed_payload

    def exit(self, plan: list | None = None, diff: list | None = None):
        """
        Formats the final response for Ansible and exits the module, handling the
        special diff cases for marketplace modules.
        """
        if diff is None:
            # If a plan exists (i.e., we are in an update/delete flow), generate its diff.
            if plan:
                diff = [cmd.to_diff() for cmd in plan]
            # If `self.order` is set, it means we just ran the creation flow.
            # This is our signal to generate the creation-specific diff.
            elif self.order:
                diff = [{"state": "Resource created.", "order_details": self.order}]
            # Otherwise, no changes were made.
            else:
                diff = []

        self.module.exit_json(
            changed=self.has_changed,
            resource=self.resource,
            order=self.order,
            diff=diff,
        )
