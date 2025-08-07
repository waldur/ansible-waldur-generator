from ansible_waldur_generator.interfaces.runner import BaseRunner


class FactsRunner(BaseRunner):
    """
    A runner for modules that only retrieve information ('facts').

    This runner implements a standard workflow for finding a single resource
    based on a name/UUID identifier and a context (like a project), then
    returning its data.
    """

    def run(self):
        """The entire logic is to find the resource and then exit."""
        self._check_existence()
        self._exit_facts()

    def _check_existence(self):
        """
        Finds a resource by its identifier (name or UUID) within a given project.
        """
        try:
            # 1. Start building the dictionary of keyword arguments for the SDK call.
            api_call_kwargs = {"client": self.client}

            # 2. Handle the main identifier (e.g., 'name') which can be a name or UUID.
            identifier_param = self.context["identifier_param"]
            value = self.module.params.get(identifier_param)

            # 3. Decide whether to use the 'list' or 'retrieve' function based on the identifier.
            if self._is_uuid(value):
                # If it's a UUID, use the more direct 'retrieve' function.
                api_call_kwargs["uuid"] = value
                sdk_func = self.context["retrieve_func"]
                result = sdk_func.sync(**api_call_kwargs)
                # Store the result in a list for consistent processing.
                self.resource = result
                return

            # If it's a name, use the 'list' function with an exact name filter.
            if value:
                api_call_kwargs["name_exact"] = value

            # 4. Resolve all context parameters (e.g., 'project').
            # The context provides a dictionary of resolvers for this purpose.
            context_resolvers = self.context.get("context_resolvers", {})
            for param_name, resolver_info in context_resolvers.items():
                if self.module.params.get(param_name):
                    # Use the shared helper to get the URL for the context resource.
                    resolved_url = self._resolve_to_url(
                        list_func=resolver_info["list_func"],
                        retrieve_func=resolver_info["retrieve_func"],
                        value=self.module.params[param_name],
                        error_message=resolver_info["error_message"],
                    )
                    # Convention: Extract the UUID from the URL and use the specified
                    # filter key to pass it to the SDK function.
                    # e.g., 'project_uuid' = '...'.
                    resolved_uuid = (
                        resolved_url.split("/")[-1] if resolved_url else None
                    )
                    filter_key = resolver_info["filter_key"]
                    if resolved_uuid:
                        api_call_kwargs[filter_key] = resolved_uuid

                sdk_func = self.context["list_func"]
                results = sdk_func.sync(**api_call_kwargs)

                if len(results) > 1:
                    self.module.warn(
                        f"Multiple {self.context['resource_type']}s found, returning the first one."
                    )

                # Store the first result.
                self.resource = results[0] if results else None

        except Exception as e:
            # Catch any exception during the lookup and fail gracefully.
            self.module.fail_json(
                msg=f"Failed to find {self.context['resource_type']}: {str(e)}"
            )

    def _exit_facts(self):
        """
        Exits the module, returning the found resource in JSON format.
        """
        if not self.resource:
            self.module.fail_json(
                msg=f"{self.context['resource_type'].capitalize()} not found with the specified parameters."
            )

        self.module.exit_json(changed=False, resource=self.resource.to_dict())
