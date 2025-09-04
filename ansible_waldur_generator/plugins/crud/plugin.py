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
        Assembles the 'runner_context' dictionary.
        """
        conf = module_config
        update_actions_context = {}
        update_fields = []

        if conf.update_config and conf.update_config.actions:
            update_actions_context = self._build_update_actions_context(
                conf.update_config.actions, api_parser
            )

        if conf.update_config and conf.update_config.fields:
            update_fields = sorted(list(dict.fromkeys(conf.update_config.fields)))

        # Prepare resolver configurations for the runner.
        resolvers_data = {}
        for name, resolver in conf.resolvers.items():
            resolvers_data[name] = {
                "url": resolver.list_operation.path if resolver.list_operation else "",
                "error_message": resolver.error_message,
            }

        # Build the map of context parameters to their API filter keys for the existence check.
        check_filter_keys = {}
        for p_conf in conf.context_params:
            check_filter_keys[p_conf.name] = p_conf.filter_key

        # The final context dictionary passed to the runner.
        runner_context = {
            "resource_type": conf.resource_type,
            "check_url": conf.check_operation.path if conf.check_operation else None,
            "check_filter_keys": check_filter_keys,
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
        params["name"] = {
            "description": f"The name of the {conf.resource_type}.",
            "type": "str",
            "required": True,
        }

        # 2. Add parameters required for nested API paths from ALL operations.
        all_path_params = set()
        for op_params in conf.path_param_maps.values():
            all_path_params.update(op_params.values())

        for ansible_param in all_path_params:
            if ansible_param not in params:
                params[ansible_param] = {
                    "name": ansible_param,
                    "type": "str",
                    "required": True,  # Path parameters are always required for the operations they map to.
                    "description": f"The parent {ansible_param} name or UUID.",
                }

        # 3. Add any context parameters used for filtering the existence check.
        for p_conf in conf.context_params:
            # Only add the parameter if it hasn't been defined by a more specific
            # configuration (like a path parameter).
            if p_conf.name not in params:
                params[p_conf.name] = {
                    "description": p_conf.description
                    or f"The name or UUID of the parent {p_conf.name} for filtering.",
                    "type": "str",
                    "required": p_conf.required,
                }

        # 4. Infer parameters from the 'create' operation's request body schema.
        if conf.create_operation and conf.create_operation.model_schema:
            schema = conf.create_operation.model_schema
            required_fields = schema.get("required", [])
            for name, prop in schema.get("properties", {}).items():
                # Skip read-only fields or parameters that have already been defined.
                if prop.get("readOnly", False) or name in params:
                    continue

                # Resolve the property schema if it's a reference. This is crucial
                # for correctly finding enums, descriptions, and types that are
                # defined in separate, reusable schema components.
                resolved_prop = prop
                if "$ref" in prop:
                    try:
                        resolved_prop = api_parser.get_schema_by_ref(prop["$ref"])
                    except ValueError:
                        # If the reference is invalid, we proceed with the original
                        # property, but it will likely lack details. This prevents a crash.
                        pass

                is_resolved = name in conf.resolvers
                description = resolved_prop.get(
                    "description", capitalize_first(name.replace("_", " "))
                )

                # If the parameter needs to be resolved, update its description to guide the user.
                if is_resolved:
                    description = f"The name or UUID of the {name}. {description}"

                choices = self._extract_choices_from_prop(resolved_prop, api_parser)

                params[name] = {
                    "name": name,
                    "type": OPENAPI_TO_ANSIBLE_TYPE_MAP.get(
                        resolved_prop.get("type", "string"), "str"
                    ),
                    "required": name in required_fields,
                    "description": description.strip(),
                    "is_resolved": is_resolved,
                    "choices": choices,
                }

        # 5. Add parameters required for any special update actions.
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
    ) -> CrudModuleConfig:
        """
        Parses the raw dictionary configuration for a single 'crud' module into a
        structured, validated, and enriched `CrudModuleConfig` object.

        This is the most critical method in the plugin, as it acts as the bridge
        between the user's YAML configuration and the structured data the generator
        needs. It is designed to be both flexible and intelligent, supporting
        multiple configuration styles:

        1.  **Inference (most concise):** If a `base_operation_id` is provided,
            the method will infer the standard `_list`, `_create`, `_destroy`, and
            `_partial_update` operations by convention. It will also infer updatable
            fields from the update operation's schema.

        2.  **Shorthand (explicit but simple):** Users can provide just the
            `operationId` string for each lifecycle stage (e.g., `create: "my_custom_create"`).

        3.  **Structured (most powerful):** Users can provide a dictionary for an
            operation to configure advanced features like `path_params` for nested
            endpoints, or `fields` and `actions` for complex updates.

        The method processes the configuration in a clear order of precedence
        (structured > shorthand > inference) and progressively builds up the
        `raw_config` dictionary before finally validating it with the Pydantic model.

        Args:
            module_key: The name of the module being generated (e.g., 'project').
            raw_config: The raw dictionary for one module from `generator_config.yaml`.
            api_parser: The shared `ApiSpecParser` instance for resolving API operations.

        Returns:
            A validated and fully populated `CrudModuleConfig` instance.

        Raises:
            ValueError: If a required operation cannot be found or inferred, or if
                        the configuration is otherwise invalid.
        """
        # --- Step 1: Initialization ---
        # Extract the base_operation_id, which is the cornerstone of inference.
        base_id = raw_config.get("base_operation_id")
        # Get the user-defined 'operations' block from the config.
        operations_config = raw_config.get("operations", {})
        # This dictionary will store path parameter mappings for all operations.
        path_param_maps = {}

        # Define a map that governs the parsing loop. It connects the keys from the
        # user's config ('check', 'create', etc.) to the field names in our Pydantic
        # model ('check_operation', 'create_operation') and the conventional suffixes
        # used for inference. For 'update', we define a priority order for suffixes.
        op_keys_map = {
            "check": ("check_operation", ["_list"]),
            "create": ("create_operation", ["_create"]),
            "destroy": ("destroy_operation", ["_destroy"]),
            "update": ("update_operation", ["_partial_update", "_update"]),
        }

        # --- Step 2: Main Operation Parsing Loop ---
        # This loop iterates through each lifecycle stage (check, create, etc.) and
        # determines the correct ApiOperation object for it based on the user's config.
        for op_key, (field_name, suffixes) in op_keys_map.items():
            op_conf = operations_config.get(op_key)
            # Allow users to explicitly disable an operation (e.g., a read-only resource).
            if op_conf is False:
                continue

            op_id = None
            # Case 1: Structured Configuration (dict). This is the most powerful format.
            if isinstance(op_conf, dict):
                op_id = op_conf.get("id")
                # If path_params are defined for this operation, store them.
                if "path_params" in op_conf:
                    path_param_maps[op_key] = op_conf["path_params"]
            # Case 2: Shorthand Configuration (string). A simple, direct mapping.
            elif isinstance(op_conf, str):
                op_id = op_conf
            # Case 3: Inference. If no config is provided, try to infer the operationId.
            elif base_id:
                for suffix in suffixes:
                    potential_id = f"{base_id}{suffix}"
                    # We query the ApiSpecParser to see if this inferred ID actually exists.
                    if api_parser.get_operation(potential_id):
                        op_id = potential_id
                        break  # Stop after finding the first valid match.

            # If an operation ID was found (by any method), resolve it into a full
            # ApiOperation object and add it to our raw_config for Pydantic validation.
            if op_id:
                raw_config[field_name] = api_parser.get_operation(op_id)

        # Store the collected path parameter mappings.
        raw_config["path_param_maps"] = path_param_maps

        # --- Step 3: Handle `update_config` (Fields and Actions) ---
        # This section handles the complex logic for updates, including inference of
        # updatable fields, which is a key convenience feature.
        update_op_conf = operations_config.get("update")
        update_operation = raw_config.get("update_operation")
        update_config = raw_config.setdefault("update_config", {})

        # If the user provided a structured config for 'update', extract the
        # explicit 'fields' and 'actions' from it.
        if isinstance(update_op_conf, dict):
            if "fields" in update_op_conf:
                update_config["fields"] = update_op_conf["fields"]
            if "actions" in update_op_conf:
                update_config["actions"] = update_op_conf["actions"]

        # **CRITICAL**: Infer updatable fields if they were not explicitly defined.
        # This is a major usability feature.
        if "fields" not in update_config and update_operation:
            # We can only infer fields if the update operation has a request body schema.
            if update_operation.model_schema:
                schema = update_operation.model_schema
                # The updatable fields are all properties in the schema that are NOT read-only.
                inferred_fields = [
                    name
                    for name, prop in schema.get("properties", {}).items()
                    if not prop.get("readOnly", False)
                ]
                if inferred_fields:
                    update_config["fields"] = inferred_fields

        # If the update_config block is still empty after all parsing and inference,
        # remove it from the raw_config to keep the final model clean.
        if not update_config:
            raw_config.pop("update_config")

        # Post-process any 'actions' by resolving their operationId strings into objects.
        update_config_raw = raw_config.get("update_config", {})
        if "actions" in update_config_raw:
            for _, action_conf in update_config_raw["actions"].items():
                action_conf["operation"] = api_parser.get_operation(
                    action_conf["operation"]
                )

        # --- Step 4: Parse Resolvers ---
        # Process the 'resolvers' block, expanding shorthand where necessary.
        for name, resolver_conf in raw_config.get("resolvers", {}).items():
            # Support shorthand `resolver: "customers"`
            if isinstance(resolver_conf, str):
                raw_config["resolvers"][name] = {
                    "list": f"{resolver_conf}_list",
                    "retrieve": f"{resolver_conf}_retrieve",
                }
            # Re-fetch the config, which may have just been expanded.
            current_resolver_conf = raw_config["resolvers"][name]
            # Resolve the operation IDs into full ApiOperation objects.
            current_resolver_conf["list_operation"] = api_parser.get_operation(
                current_resolver_conf["list"]
            )
            current_resolver_conf["retrieve_operation"] = api_parser.get_operation(
                current_resolver_conf["retrieve"]
            )

        # --- Step 5: Final Validation and Instantiation ---
        # At this point, `raw_config` is fully populated with enriched data.
        # We pass it to the Pydantic model for final validation and type coercion.
        module_config = CrudModuleConfig(**raw_config)

        # Perform critical post-validation checks to prevent generating a broken module.
        if not module_config.check_operation:
            raise ValueError(f"Module '{module_key}' must have a 'check' operation.")
        if not module_config.create_operation:
            raise ValueError(f"Module '{module_key}' must have a 'create' operation.")

        # Validate that any `context_params` are configured correctly against the
        # OpenAPI spec for the `check_operation`.
        self._validate_context_params(
            module_key=module_key,
            context_params=module_config.context_params,
            target_operation=module_config.check_operation,
            api_parser=api_parser,
        )

        return module_config
