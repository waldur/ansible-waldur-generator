from ansible_waldur_generator.interfaces.runner import BaseRunner


class CrudRunner(BaseRunner):
    """
    Handles the core logic for a standard CRUD-based Ansible module.
    """

    def run(self):
        """
        The main execution path of the runner.
        """
        self.check_existence()
        if self.module.check_mode:
            self.handle_check_mode()
            return
        if self.resource:
            if self.module.params["state"] == "absent":
                self.delete()
        else:
            if self.module.params["state"] == "present":
                self.create()
        self.exit()

    def check_existence(self):
        """
        Checks if the resource exists.
        """
        params = {"name_exact": self.module.params["name"]}
        data = self._send_request("GET", self.context["api_path"], query_params=params)
        self.resource = data[0] if data else None

    def create(self):
        """
        Creates the resource.
        """
        payload = {
            key: self.module.params[key]
            for key in self.context["model_param_names"]
            if key in self.module.params and self.module.params[key] is not None
        }
        for name, resolver in self.context.get("resolvers", {}).items():
            if self.module.params.get(name):
                payload[name] = self._resolve_to_url(
                    path=resolver["url"],
                    value=self.module.params[name],
                    error_message=resolver["error_message"],
                )

        self.resource = self._send_request(
            "POST", self.context["api_path"], data=payload
        )
        self.has_changed = True

    def delete(self):
        """
        Deletes the resource.
        """
        if self.resource:
            path = f"{self.context['api_path']}{self.resource['uuid']}/"
            self._send_request("DELETE", path)
            self.has_changed = True
            self.resource = None

    def handle_check_mode(self):
        """
        Predicts changes in check_mode.
        """
        if self.module.params["state"] == "present" and not self.resource:
            self.has_changed = True
        elif self.module.params["state"] == "absent" and self.resource:
            self.has_changed = True
        self.exit()

    def exit(self):
        """
        Formats the final resource state and exits the module.
        """
        self.module.exit_json(changed=self.has_changed, resource=self.resource)
