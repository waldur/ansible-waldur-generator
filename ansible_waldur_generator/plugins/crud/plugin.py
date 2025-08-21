from typing import Dict, Any, List

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator
from ansible_waldur_generator.models import (
    AnsibleModuleParams,
)
from ansible_waldur_generator.helpers import (
    AUTH_OPTIONS,
    OPENAPI_TO_ANSIBLE_TYPE_MAP,
    capitalize_first,
)
from ansible_waldur_generator.interfaces.plugin import BasePlugin
from ansible_waldur_generator.plugins.crud.config import (
    CrudModuleConfig,
)

# A base dictionary for the module's argument_spec, containing common
# parameters required for every module, such as authentication and state.
BASE_SPEC = {
    **AUTH_OPTIONS,  # Includes 'api_url' and 'access_token'
    "state": {
        "description": "Should the resource be present or absent.",
        "choices": ["present", "absent"],
        "default": "present",
        "type": "str",
    },
}


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
                update_actions_context[key] = {
                    "path": action.operation.path,
                    "param": action.param,
                }

        # The final context dictionary passed to the runner.
        return {
            "resource_type": conf.resource_type,
            # API paths for each lifecycle stage.
            "list_path": conf.check_operation.path,
            "create_path": conf.create_operation.path,
            "destroy_path": conf.destroy_operation.path,
            "update_path": conf.update_operation.path
            if conf.update_operation
            else None,
            # List of parameter names expected in the 'create' request body.
            "model_param_names": self._get_model_param_names(module_config),
            # Mapping for nested endpoint path parameters.
            "path_param_maps": conf.path_param_maps,
            # List of fields to check for simple PATCH updates.
            "update_fields": conf.update_config.fields if conf.update_config else [],
            # Dictionary of complex update actions (e.g., set_rules).
            "update_actions": update_actions_context,
            "resolvers": resolvers_data,
        }

    def _get_model_param_names(self, module_config: CrudModuleConfig) -> List[str]:
        """Helper to get a list of parameter names from the create operation's request body schema."""
        if not module_config.create_operation:
            return []
        schema = module_config.create_operation.model_schema
        if not schema or "properties" not in schema:
            return []
        # Exclude any fields marked as 'readOnly' as they are server-generated.
        return [
            name
            for name, prop in schema["properties"].items()
            if not prop.get("readOnly", False)
        ]

    def _build_parameters(
        self, module_config: CrudModuleConfig, api_parser: ApiSpecParser
    ) -> AnsibleModuleParams:
        """
        Creates the complete dictionary of Ansible module parameters by combining
        explicitly defined parameters with those inferred from the API specification.
        """
        params: AnsibleModuleParams = {**BASE_SPEC}
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

    def _validate_config(self, config: Dict[str, Any]):
        """Performs basic validation on the raw module configuration."""
        # Ensure all mandatory operations are defined.
        operations = config.get("operations", {})
        required = ["list", "create", "destroy"]
        missing = [op for op in required if op not in operations]
        if missing:
            raise ValueError(f"Missing required operations in config: {missing}")

        # Ensure all resolvers are well-formed.
        for name, resolver in config.get("resolvers", {}).items():
            if "list" not in resolver or "retrieve" not in resolver:
                raise ValueError(
                    f"Resolver '{name}' is missing list/retrieve operations"
                )

    def _parse_configuration(
        self,
        module_key: str,
        raw_config: Dict[str, Any],
        api_parser: ApiSpecParser,
    ):
        self._validate_config(raw_config)

        # 1. Parse all operationIds from the config into full ApiOperation objects.
        operations = raw_config["operations"]
        raw_config["check_operation"] = api_parser.get_operation(operations["list"])
        raw_config["create_operation"] = api_parser.get_operation(operations["create"])
        raw_config["destroy_operation"] = api_parser.get_operation(
            operations["destroy"]
        )

        if "update" in operations:
            raw_config["update_operation"] = api_parser.get_operation(
                operations["update"]
            )

        update_config_raw = raw_config.get("update_config", {})
        if update_config_raw:
            actions_raw = update_config_raw.get("actions", {})
            for _, action_conf in actions_raw.items():
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
            resolver_conf["list_operation"] = api_parser.get_operation(
                resolver_conf["list"]
            )
            resolver_conf["retrieve_operation"] = api_parser.get_operation(
                resolver_conf["retrieve"]
            )

        # 2. Create a strongly-typed configuration object using Pydantic.
        return CrudModuleConfig(**raw_config)
