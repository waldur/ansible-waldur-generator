from typing import Dict, Any, List

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator
from ansible_waldur_generator.models import (
    AnsibleModuleParams,
)
from ansible_waldur_generator.helpers import (
    AUTH_OPTIONS,
    OPENAPI_TO_ANSIBLE_TYPE_MAP,
    WAITER_OPTIONS,
    capitalize_first,
)
from ansible_waldur_generator.interfaces.plugin import BasePlugin
from ansible_waldur_generator.plugins.crud.config import (
    CrudModuleConfig,
)


class CrudPlugin(BasePlugin):
    """
    A generator plugin for creating Ansible modules that manage resources
    following a standard Create, Read, Update, Delete (CRUD) pattern.

    This plugin is extended to support more complex scenarios, including:
    - Creating resources via a nested endpoint (e.g., `/parents/{uuid}/children/`).
    - Updating resources using both simple field changes (PATCH) and special
      action endpoints (POST), managed intelligently within a single `state: present`.
    """

    def get_type_name(self) -> str:
        """Returns the unique identifier for this plugin type."""
        return "crud"

    def _build_return_block(
        self, module_config: CrudModuleConfig, return_generator: ReturnBlockGenerator
    ) -> Dict[str, Any] | None:
        """
        Constructs the RETURN block for the module's documentation.

        It infers the structure of the returned resource object from the success
        response of the 'create' operation, which is assumed to return the complete
        resource representation.
        """
        return_block = None
        # Get the raw OpenAPI specification for the 'create' operation.
        create_op_spec = module_config.create_operation.raw_spec
        # Use the ReturnBlockGenerator to parse the schema and generate the documentation structure.
        return_content = return_generator.generate_for_operation(create_op_spec)

        # Format the generated content into the standard Ansible RETURN structure.
        if return_content:
            return_block = {
                "resource": {
                    "description": f"The state of the {module_config.resource_type} after the operation.",
                    "type": "dict",
                    "returned": "on success",
                    "contains": return_content,
                }
            }
        return return_block

    def _build_runner_context(
        self, module_config: CrudModuleConfig, api_parser
    ) -> Dict[str, Any]:
        """

        Assembles the 'runner_context' dictionary. This context is serialized into
        the generated module and provides the runner with all the necessary
        API details and logic mappings to perform its tasks.
        """
        conf = module_config

        # Prepare resolver configurations for the runner.
        resolvers_data = {}
        for name, resolver in conf.resolvers.items():
            resolvers_data[name] = {
                "url": resolver.list_operation.path if resolver.list_operation else "",
                "error_message": resolver.error_message,
            }

        # Prepare update action configurations for the runner.
        update_actions_context = {}
        if conf.update_config and conf.update_config.actions:
            for key, action in conf.update_config.actions.items():
                request_body_schema = action.operation.model_schema or {}
                # If the schema is a direct array, we pass the data directly.
                # Otherwise, we wrap it in an object with the parameter name as the key.
                body_format_is_object = request_body_schema.get("type") == "object"

                update_actions_context[key] = {
                    "path": action.operation.path,
                    "param": action.param,
                    "check_field": action.check_field
                    or action.param,  # Default check_field to param name
                    "wrap_in_object": body_format_is_object,
                }

        update_fields = []
        if module_config.update_config:
            update_fields = sorted(
                list(dict.fromkeys(module_config.update_config.fields))
            )

        # The final context dictionary passed to the runner.
        runner_context = {
            "resource_type": conf.resource_type,
            # API paths for each lifecycle stage.
            "list_path": conf.check_operation.path if conf.check_operation else None,
            "create_path": conf.create_operation.path
            if conf.create_operation
            else None,
            "destroy_path": conf.destroy_operation.path
            if conf.destroy_operation
            else None,
            "update_path": conf.update_operation.path
            if conf.update_operation
            else None,
            # List of parameter names expected in the 'create' request body.
            "model_param_names": self._get_model_param_names(module_config),
            # Mapping for nested endpoint path parameters.
            "path_param_maps": conf.path_param_maps,
            # List of fields to check for simple PATCH updates.
            "update_fields": update_fields,
            # Dictionary of complex update actions (e.g., set_rules).
            "update_actions": update_actions_context,
            "resolvers": resolvers_data,
            # Add the generic polling path. The destroy path is the detail view.
            "resource_detail_path": conf.destroy_operation.path
            if conf.destroy_operation
            else None,
        }

        if module_config.wait_config:
            runner_context["wait_config"] = module_config.wait_config.model_dump()

        return runner_context

    def _get_model_param_names(self, module_config: CrudModuleConfig) -> List[str]:
        """Helper to get a list of parameter names from the create operation's request body schema."""
        if not module_config.create_operation:
            return []
        schema = module_config.create_operation.model_schema
        if not schema or "properties" not in schema:
            return []
        # Exclude any fields marked as 'readOnly' as they are server-generated.
        param_names = [
            name
            for name, prop in schema["properties"].items()
            if not prop.get("readOnly", False)
        ]
        return sorted(param_names)

    def _build_parameters(
        self, module_config: CrudModuleConfig, api_parser: ApiSpecParser
    ) -> AnsibleModuleParams:
        """
        Creates the complete dictionary of Ansible module parameters by combining
        explicitly defined parameters with those inferred from the API specification.
        """
        params: AnsibleModuleParams = {
            **AUTH_OPTIONS,  # Includes 'api_url' and 'access_token'
            **WAITER_OPTIONS,  # Includes 'state', 'wait', 'timeout', 'interval'
        }
        conf = module_config

        # 1. Add parameters used for checking existence (e.g., 'name').
        for p in conf.check_operation_config.get("params", []):
            p["type"] = OPENAPI_TO_ANSIBLE_TYPE_MAP.get(p.get("type", "str"), "str")
            params[p["name"]] = p

        # 2. Add parameters required for nested API paths (e.g., the parent resource 'tenant').
        # This is derived from the 'path_param_maps' configuration.
        create_path_maps = conf.path_param_maps.get("create", {})
        for _, ansible_param in create_path_maps.items():
            if ansible_param not in params:
                params[ansible_param] = {
                    "name": ansible_param,
                    "type": "str",
                    "required": True,  # Path parameters are always required for creation.
                    "description": f"The parent {ansible_param} name or UUID for creating the resource.",
                }

        # 3. Infer parameters from the 'create' operation's request body schema.
        if conf.create_operation and conf.create_operation.model_schema:
            schema = conf.create_operation.model_schema
            required_fields = schema.get("required", [])
            for name, prop in schema.get("properties", {}).items():
                # Skip read-only fields or parameters that have already been defined.
                if prop.get("readOnly", False) or name in params:
                    continue

                is_resolved = name in conf.resolvers
                description = prop.get(
                    "description", capitalize_first(name.replace("_", " "))
                )

                # If the parameter needs to be resolved, update its description to guide the user.
                if is_resolved:
                    description = f"The name or UUID of the {name}. {description}"

                choices = self._extract_choices_from_prop(prop, api_parser)

                params[name] = {
                    "name": name,
                    "type": OPENAPI_TO_ANSIBLE_TYPE_MAP.get(
                        prop.get("type", "string"), "str"
                    ),
                    "required": name in required_fields,
                    "description": description.strip(),
                    "is_resolved": is_resolved,
                    "choices": choices,
                }

        # 4. Add parameters required for any special update actions.
        if conf.update_config:
            for action_key, action_conf in conf.update_config.actions.items():
                param_name = action_conf.param
                # Add the parameter if it's not already defined and has a schema.
                if param_name not in params and action_conf.operation.model_schema:
                    schema = action_conf.operation.model_schema
                    params[param_name] = {
                        "name": param_name,
                        "type": OPENAPI_TO_ANSIBLE_TYPE_MAP.get(
                            schema.get("type", "string"), "str"
                        ),
                        "required": False,  # Update actions are optional.
                        "description": schema.get(
                            "description", f"Parameter for the '{action_key}' action."
                        ),
                    }

        return params

    def _build_examples(
        self,
        module_config: CrudModuleConfig,
        module_name: str,
        collection_namespace: str,
        collection_name: str,
        schema_parser: ReturnBlockGenerator,
    ) -> List[Dict[str, Any]]:
        """Builds realistic examples by calling the shared helper from BasePlugin."""

        # For CRUD modules, the base parameters for examples are determined by the
        # path parameters needed for creation.
        base_params = {}
        path_param_maps = module_config.path_param_maps.get("create", {})
        for _, ansible_param in path_param_maps.items():
            base_params[ansible_param] = (
                f"{ansible_param.replace('_', ' ').capitalize()} name or UUID"
            )

        return super()._build_examples_from_schema(
            module_config=module_config,
            module_name=module_name,
            collection_namespace=collection_namespace,
            collection_name=collection_name,
            schema_parser=schema_parser,
            create_schema=module_config.create_operation.model_schema or {},
            base_params=base_params,
            delete_identifier_param="name",
        )

    def _parse_configuration(
        self,
        module_key: str,
        raw_config: Dict[str, Any],
        api_parser: ApiSpecParser,
    ):
        base_id = raw_config.get("base_operation_id")
        operations_config = raw_config.get("operations", {})
        path_param_maps = {}

        op_map = {
            "check": ("check_operation", "_list"),
            "create": ("create_operation", "_create"),
            "delete": ("destroy_operation", "_destroy"),
            "update": ("update_operation", "_partial_update"),
        }

        for op_key, (field_name, op_suffix) in op_map.items():
            op_conf = operations_config.get(op_key, None)

            # If the user explicitly disables this op, skip it.
            if op_conf is False:
                continue

            op_id = None
            # Case 1: Handle explicit overrides (str or dict)
            if isinstance(op_conf, (str, dict)):
                if isinstance(op_conf, str):
                    op_id = op_conf
                else:  # dict
                    op_id = op_conf.get("id")
                    if "path_params" in op_conf:
                        path_param_maps[op_key] = op_conf["path_params"]
                    if op_key == "update":
                        if "fields" in op_conf:
                            raw_config.setdefault("update_config", {})["fields"] = (
                                op_conf["fields"]
                            )
                        if "actions" in op_conf:
                            raw_config.setdefault("update_config", {})["actions"] = (
                                op_conf["actions"]
                            )
            # Case 2: Infer the operation if it's not disabled, not overridden, and not 'false'.
            elif op_conf is not False:
                if not base_id:
                    raise ValueError(
                        f"Cannot infer operation '{op_key}' because `base_operation_id` is not defined."
                    )
                op_id = f"{base_id}{op_suffix}"

            if op_id:
                raw_config[field_name] = api_parser.get_operation(op_id)

        raw_config["path_param_maps"] = path_param_maps

        # Post-process actions within update_config
        update_config_raw = raw_config.get("update_config", {})
        if "actions" in update_config_raw:
            for _, action_conf in update_config_raw["actions"].items():
                action_conf["operation"] = api_parser.get_operation(
                    action_conf["operation"]
                )

        # Set default configuration for the 'check' operation.
        raw_config["check_operation_config"] = {
            "params": [
                {
                    "name": "name",
                    "type": "str",
                    "required": True,
                    "description": f"The name of the {module_key} to check/create/delete.",
                    "maps_to": "name_exact",
                }
            ]
        }

        # Parse resolver operationIds as well.
        for name, resolver_conf in raw_config.get("resolvers", {}).items():
            if isinstance(resolver_conf, str):
                # Expand shorthand
                raw_config["resolvers"][name] = {
                    "list": f"{resolver_conf}_list",
                    "retrieve": f"{resolver_conf}_retrieve",
                }
            # Re-fetch the (potentially new) conf
            current_resolver_conf = raw_config["resolvers"][name]
            current_resolver_conf["list_operation"] = api_parser.get_operation(
                current_resolver_conf["list"]
            )
            current_resolver_conf["retrieve_operation"] = api_parser.get_operation(
                current_resolver_conf["retrieve"]
            )

        module_config = CrudModuleConfig(**raw_config)

        # Final validation after parsing
        if not module_config.check_operation:
            raise ValueError(f"Module '{module_key}' must have a 'check' operation.")
        if not module_config.create_operation:
            raise ValueError(f"Module '{module_key}' must have a 'create' operation.")

        return module_config
