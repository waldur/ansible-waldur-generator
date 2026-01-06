from ansible_waldur_generator.interfaces.resolver import ParameterResolver
from ansible_waldur_generator.interfaces.runner import BaseRunner
from ansible_waldur_generator.interfaces.command import Command


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

    def check_existence(self):
        """
        Check for resource existence, prioritizing the offering-based filter if present.
        """
        # If 'offering' is specified, we must filter by it.
        # This prevents identical resource names in different offerings from
        # being treated as the same resource.
        if self.module.params.get("offering"):
            marketplace_url = self.context.get("marketplace_resource_check_url")
            if not marketplace_url:
                # Should not happen if plugin is configured correctly
                self.module.fail_json(
                    msg="Configuration error: 'marketplace_resource_check_url' missing from context."
                )
                return

            # Resolve the offering to get its UUID
            offering_uuid = self.resolver.resolve(
                "offering", self.module.params["offering"]
            )
            if not offering_uuid:
                self.module.fail_json(
                    msg=f"Could not resolve offering '{self.module.params['offering']}' to a valid UUID string."
                )
                return

            # The resolver returns a URL, extract the UUID
            if "/" in offering_uuid:
                offering_uuid = offering_uuid.rstrip("/").split("/")[-1]

            # Resolve project to get its UUID for filtering
            project_uuid = None
            if self.module.params.get("project"):
                project_url = self.resolver.resolve(
                    "project", self.module.params["project"]
                )
                if project_url and "/" in project_url:
                    project_uuid = project_url.rstrip("/").split("/")[-1]

            # Build query parameters
            query_params = {
                "offering_uuid": offering_uuid,
            }

            # Add project filter if available
            if project_uuid:
                query_params["project_uuid"] = project_uuid

            # Add name filter
            # Order modules typically use 'name_exact' for name filtering
            # We check context for specific name param name or default to 'name_exact'
            name_param = self.context.get("name_query_param", "name_exact")
            if self.module.params.get("name"):
                query_params[name_param] = self.module.params["name"]

            # Filter out terminated resources at the API level
            query_params["state"] = [
                "OK",
                "Erred",
                "Creating",
                "Updating",
                "Terminating",
            ]

            # Query marketplace resources
            response, _ = self.send_request(
                "GET", marketplace_url, query_params=query_params
            )

            if response and len(response) > 0:
                # Filter to only resources with valid scopes
                # (Scope is a field value, not a filterable query param)
                active_resources = [r for r in response if r.get("scope")]

                if len(active_resources) > 1:
                    self.module.fail_json(
                        msg=f"Multiple active resources found for name '{self.module.params.get('name')}' in the specified offering. Please ensure resource names are unique."
                    )
                    return

                if len(active_resources) == 0:
                    # No active resources found
                    self.resource = None
                    return

                marketplace_resource = active_resources[0]
                scope_url = marketplace_resource.get("scope")

                # Follow the scope URL to get the actual plugin resource
                resource, _ = self.send_request("GET", scope_url)
                if resource:
                    self.resource = resource
                    # Important: Attach the marketplace UUID to the resource object
                    # so that deletion logic can find it later (as deletion often targets the marketplace resource)
                    self.resource["marketplace_resource_uuid"] = marketplace_resource[
                        "uuid"
                    ]
                    return
                else:
                    # Scope URL exists but resource not found? treat as not found.
                    self.resource = None
                    return
            else:
                self.resource = None
                return

        # Fallback to standard check_existence if no offering is specified
        super().check_existence()

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

        # --- 1. Validate required parameters ---
        required_for_create = self.context.get("required_for_create", [])
        for key in required_for_create:
            if self.module.params.get(key) is None:
                self.module.fail_json(
                    msg=f"Parameter '{key}' is required when state is 'present' for a new resource."
                )

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

        # Define the configuration for the generic waiter. This tells the BaseRunner
        # how to poll the order's status after it's created.
        wait_config = {
            "polling_path": "/api/marketplace-orders/{uuid}/",
            "state_field": "state",
            "ok_states": ["done"],
            "erred_states": ["erred", "rejected", "canceled"],
            # The order's UUID comes from the body of the POST response.
            "uuid_source": {"location": "result_body", "key": "uuid"},
            # A special flag telling the waiter to re-fetch the final resource
            # state upon completion, rather than returning the order object.
            "refetch_resource": True,
        }

        # The entire creation workflow is now encapsulated in this single Command.
        return [
            Command(
                self,
                method="POST",
                path="/api/marketplace-orders/",
                command_type="order",
                data=order_payload,
                description=f"Create {self.context['resource_type']} via marketplace order",
                wait_config=wait_config,
            )
        ]

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
        return [
            Command(
                self,
                method="POST",
                path=path,
                command_type="delete",
                data=termination_payload,
                description=f"Terminate {self.context['resource_type']} '{self.resource.get('name', self.resource.get('uuid'))}'",
            )
        ]
