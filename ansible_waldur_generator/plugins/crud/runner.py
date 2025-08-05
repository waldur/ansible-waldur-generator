import uuid
from ansible.module_utils.basic import AnsibleModule
from waldur_api_client.client import AuthenticatedClient


def _is_uuid(val):
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


class CrudResourceRunner:
    """
    Handles the core logic for a standard CRUD-based Ansible module.
    This class is generic and is configured by passing specific SDK functions
    and model classes during initialization.
    """

    def __init__(self, module: AnsibleModule, context: dict):
        self.module = module
        self.context = context  # The context contains all the generator-produced info
        self.client = AuthenticatedClient(
            base_url=module.params["api_url"], token=module.params["access_token"]
        )
        self.has_changed = False
        self.resource = None

    def run(self):
        """The main execution path of the runner."""
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
        """Checks if the resource exists."""
        try:
            # Get the function from the context
            check_func = self.context["existence_check_func"]
            resources = check_func.sync(
                client=self.client, name_exact=self.module.params["name"]
            )
            self.resource = resources[0] if resources else None
        except Exception as e:
            self.module.fail_json(
                msg=f"Failed to check for {self.context['resource_type']} existence: {e}"
            )

    def create(self):
        """Creates the resource."""
        try:
            model_params = {
                key: self.module.params[key]
                for key in self.context["model_param_names"]
                if key in self.module.params and self.module.params[key] is not None
            }
            # Resolve any required parameters
            for name, resolver in self.context.get("resolvers", {}).items():
                if self.module.params.get(name):
                    model_params[name] = self._resolve_to_url(
                        list_func=resolver["list_func"],
                        retrieve_func=resolver["retrieve_func"],
                        value=self.module.params[name],
                        error_message=resolver["error_message"],
                    )

            model_class = self.context["present_create_model_class"]
            create_func = self.context["present_create_func"]

            request_body = model_class(**model_params)
            self.resource = create_func.sync(client=self.client, body=request_body)
            self.has_changed = True
        except Exception as e:
            self.module.fail_json(
                msg=f"Failed to create {self.context['resource_type']}: {e}"
            )

    def delete(self):
        """Deletes the resource."""
        try:
            destroy_func = self.context["absent_destroy_func"]
            path_param = self.context["absent_destroy_path_param"]
            destroy_func.sync_detailed(
                client=self.client, uuid=getattr(self.resource, path_param)
            )
            self.has_changed = True
            self.resource = None
        except Exception as e:
            self.module.fail_json(
                msg=f"Failed to delete {self.context['resource_type']}: {e}"
            )

    def handle_check_mode(self):
        """Predicts changes in check_mode."""
        if self.module.params["state"] == "present" and not self.resource:
            self.has_changed = True
        elif self.module.params["state"] == "absent" and self.resource:
            self.has_changed = True
        self.exit()

    def exit(self):
        """Formats the final resource state and exits the module."""
        resource_dict = (
            self.resource.to_dict()
            if self.resource and hasattr(self.resource, "to_dict")
            else None
        )
        self.module.exit_json(changed=self.has_changed, resource=resource_dict)

    def _resolve_to_url(self, list_func, retrieve_func, value, error_message):
        if not value:
            return None
        if str(value).startswith(("http://", "https://")):
            return value
        try:
            if _is_uuid(value):
                resource = retrieve_func.sync(client=self.client, uuid=value)
                resources = [resource] if resource else []
            else:
                resources = list_func.sync(client=self.client, name_exact=value)
            if not resources:
                self.module.fail_json(msg=error_message.format(value=value))
            if len(resources) > 1:
                self.module.fail_json(msg=f"Multiple resources found for '{value}'.")
            return resources[0].url
        except Exception as e:
            self.module.fail_json(msg=f"Failed to resolve '{value}': {e}")
