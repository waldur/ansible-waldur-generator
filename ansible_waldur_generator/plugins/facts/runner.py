from ansible_waldur_generator.interfaces.runner import BaseRunner


class FactsRunner(BaseRunner):
    """
    A runner for modules that only retrieve information ('facts').
    """

    def run(self):
        """
        The main execution path of the runner.
        """
        self._check_existence()
        self._exit_facts()

    def _check_existence(self):
        """
        Finds a resource by its identifier (name or UUID) within a given project.
        """
        identifier_param = self.context["identifier_param"]
        value = self.module.params.get(identifier_param)

        if self._is_uuid(value):
            self.resource = self._send_request(
                "GET", self.context["retrieve_url"], path_params={"uuid": value}
            )
            return

        params = {}
        if value:
            params["name_exact"] = value

        context_resolvers = self.context.get("context_resolvers", {})
        for param_name, resolver_info in context_resolvers.items():
            if self.module.params.get(param_name):
                resolved_url = self._resolve_to_url(
                    path=resolver_info["url"],
                    value=self.module.params[param_name],
                    error_message=resolver_info["error_message"],
                )
                if resolved_url:
                    url_parts = [part for part in resolved_url.split("/") if part]
                    resolved_uuid = url_parts[-1] if url_parts else None
                else:
                    resolved_uuid = None
                filter_key = resolver_info["filter_key"]
                if resolved_uuid:
                    params[filter_key] = resolved_uuid

        data = self._send_request("GET", self.context["list_url"], query_params=params)
        if data and len(data) > 1:
            self.module.warn(
                f"Multiple {self.context['resource_type']}s found, returning the first one."
            )
        self.resource = data[0] if data else None

    def _exit_facts(self):
        """
        Exits the module, returning the found resource in JSON format.
        """
        if not self.resource:
            self.module.fail_json(
                msg=f"{self.context['resource_type'].capitalize()} not found with the specified parameters."
            )
            return
        self.module.exit_json(changed=False, resource=self.resource)
