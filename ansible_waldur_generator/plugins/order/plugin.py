import re
from typing import Dict, Any, List

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator
from ansible_waldur_generator.models import AnsibleModuleParams
from ansible_waldur_generator.helpers import (
    AUTH_OPTIONS,
    OPENAPI_TO_ANSIBLE_TYPE_MAP,
    capitalize_first,
)
from ansible_waldur_generator.interfaces.plugin import BasePlugin
from ansible_waldur_generator.plugins.order.config import (
    OrderModuleResolver,
    ParameterConfig,
    OrderModuleConfig,
)

BASE_SPEC = {
    **AUTH_OPTIONS,
    "state": {
        "description": "Should the resource be present or absent.",
        "choices": ["present", "absent"],
        "default": "present",
        "type": "str",
    },
    "wait": {
        "description": "A boolean value that defines whether to wait for the order to complete.",
        "default": True,
        "type": "bool",
    },
    "timeout": {
        "description": "The maximum number of seconds to wait for the order to complete.",
        "default": 600,
        "type": "int",
    },
    "interval": {
        "description": "The interval in seconds for polling the order status.",
        "default": 20,
        "type": "int",
    },
}


class OrderPlugin(BasePlugin):
    """Plugin for handling 'order' module types."""

    def get_type_name(self) -> str:
        return "order"

    def _build_return_block(
        self,
        module_config: OrderModuleConfig,
        return_generator: ReturnBlockGenerator,
    ) -> Dict[str, Any]:
        return_content = None
        if module_config.existence_check_op:
            existence_check_op_spec = module_config.existence_check_op.raw_spec
            return_content = return_generator.generate_for_operation(
                existence_check_op_spec
            )

        return_block_dict = {}
        if return_content:
            return_block_dict = {
                "resource": {
                    "description": f"A dictionary describing the {module_config.resource_type} after a successful 'present' state.",
                    "type": "dict",
                    "returned": "on success when state is 'present'",
                    "contains": return_content,
                }
            }
        return return_block_dict

    def _build_spec_for_param(
        self,
        p_conf: ParameterConfig,
        api_parser: ApiSpecParser,
        module_config: OrderModuleConfig,
    ) -> dict:
        """
        Recursively builds the argument_spec dict for a single parameter,
        resolving any references ($ref) it encounters.
        """
        p_conf_to_process = p_conf

        # --- 1. Resolve Reference ---
        # If the current parameter is a reference, replace it with a fully parsed
        # ParameterConfig object created from the resolved schema.
        if p_conf.ref:
            ref_path = p_conf.ref
            resolved_schema_dict = api_parser.get_schema_by_ref(ref_path)

            # Convert the resolved raw dictionary into a ParameterConfig object.
            # We preserve the original 'name' and 'required' status from the point of reference.
            p_conf_to_process = self._create_param_config_from_schema(
                name=p_conf.name,
                prop=resolved_schema_dict,
                required_list=[p_conf.name] if p_conf.required else [],
                api_parser=api_parser,
                module_config=module_config,
            )

        param_spec = {}

        # 2. Determine Ansible Type
        # This line will now work correctly.
        param_type = OPENAPI_TO_ANSIBLE_TYPE_MAP.get(p_conf_to_process.type, "str")
        param_spec["type"] = param_type

        # 3. Set basic attributes
        param_spec["required"] = p_conf_to_process.required
        if p_conf_to_process.choices:
            param_spec["choices"] = p_conf_to_process.choices

        param_spec["description"] = self._get_prop_description(
            p_conf_to_process.name, p_conf_to_process.model_dump(), module_config
        )

        # 4. Handle Complex Types Recursively
        if param_type == "dict" and p_conf_to_process.properties:
            suboptions = {}
            for sub_p_conf in p_conf_to_process.properties:
                # Recursive call, passing all necessary context along
                suboptions[sub_p_conf.name] = self._build_spec_for_param(
                    sub_p_conf, api_parser, module_config
                )
            if suboptions:
                param_spec["suboptions"] = suboptions

        elif param_type == "list" and p_conf_to_process.items:
            # Recursively build the spec for the items in the list
            item_spec = self._build_spec_for_param(
                p_conf_to_process.items, api_parser, module_config
            )

            item_type = item_spec.get("type", "str")
            param_spec["elements"] = item_type

            # If the list contains complex objects, copy their suboptions
            if item_type == "dict" and "suboptions" in item_spec:
                param_spec["suboptions"] = item_spec["suboptions"]

        return param_spec

    def _build_parameters(
        self, module_config: OrderModuleConfig, api_parser: ApiSpecParser
    ) -> AnsibleModuleParams:
        params: AnsibleModuleParams = {**BASE_SPEC}

        params["name"] = {
            "type": "str",
            "required": True,
            "description": f"The name of the {module_config.resource_type}.",
        }
        params["project"] = {
            "type": "str",
            "required": True,
            "description": "The name or UUID of the project.",
        }
        params["offering"] = {
            "type": "str",
            "required": True,
            "description": "The name or UUID of the marketplace offering.",
        }
        params["plan"] = {
            "type": "str",
            "required": False,
            "description": "URL of the marketplace plan.",
        }
        if module_config.has_limits:
            params["limits"] = {
                "type": "object",
                "required": False,
                "description": "Marketplace resource limits for limit-based billing.",
            }
        params["description"] = {
            "type": "str",
            "required": False,
            "description": f"A description for the {module_config.resource_type}.",
        }

        for p_conf in module_config.attribute_params:
            params[p_conf.name] = self._build_spec_for_param(
                p_conf, api_parser, module_config
            )

        return params

    def _build_runner_context(
        self, module_config: OrderModuleConfig, api_parser
    ) -> Dict[str, Any]:
        resolvers_data = {}
        for name, resolver in module_config.resolvers.items():
            resolvers_data[name] = {
                "url": resolver.list_operation.path if resolver.list_operation else "",
                "error_message": resolver.error_message,
                "filter_by": [f.model_dump() for f in resolver.filter_by],
            }

        attribute_param_names = [p.name for p in module_config.attribute_params]
        attribute_param_names.append("description")

        return {
            "resource_type": module_config.resource_type,
            "existence_check_url": module_config.existence_check_op.path
            if module_config.existence_check_op
            else "",
            "existence_check_filter_keys": {"project": "project_uuid"},
            "update_url": module_config.update_op.path
            if module_config.update_op
            else None,
            "update_check_fields": module_config.update_check_fields,
            "attribute_param_names": list(set(attribute_param_names)),
            "resolvers": resolvers_data,
        }

    def _build_schema_for_attributes(
        self, module_config: OrderModuleConfig
    ) -> Dict[str, Any]:
        """
        Constructs a JSON-schema-like dictionary from the list of attribute
        parameters. This "virtual" schema can then be used by the example generator.
        """
        properties = {}
        # The 'name' and 'description' are top-level Ansible params but map to
        # the 'attributes' dict in the order payload.
        properties["name"] = {"type": "string"}
        properties["description"] = {"type": "string"}

        # Recursively build schema for configured attribute params
        def param_to_prop(p_conf: ParameterConfig):
            # Priority 1: If the parameter is a direct reference to another schema
            # component, pass the reference along. The schema parser knows how to
            # resolve this.
            if p_conf.ref:
                return {"$ref": p_conf.ref}

            prop: dict[str, Any] = {"type": p_conf.type}
            if p_conf.type == "array":
                # For arrays, we must correctly define the 'items' schema.
                if p_conf.is_resolved:
                    # Case A: A simple list of names/UUIDs (e.g., security_groups for an instance).
                    # The user provides a list of strings.
                    prop["items"] = {"type": "string"}
                elif p_conf.items:
                    # Case B: An array of complex objects (e.g., rules for a security group).
                    # We recurse to build the schema for the nested item object.
                    prop["items"] = param_to_prop(p_conf.items)
                # If neither, it's an un-typed array, which is rare.
                # The default sample generator will produce `[]`.

            elif p_conf.properties:
                # For nested objects that are not arrays.
                prop["properties"] = {
                    sub.name: param_to_prop(sub) for sub in p_conf.properties
                }
            return prop

        for p_conf in module_config.attribute_params:
            properties[p_conf.name] = param_to_prop(p_conf)

        return {"type": "object", "properties": properties}

    def _build_examples(
        self,
        module_config: OrderModuleConfig,
        module_name: str,
        collection_namespace: str,
        collection_name: str,
        schema_parser: ReturnBlockGenerator,
    ) -> List[Dict[str, Any]]:
        """Builds realistic examples using the shared helper from BasePlugin."""
        # Step 1: Construct the virtual schema for the 'attributes' payload.
        attributes_schema = self._build_schema_for_attributes(module_config)

        # Base parameters specific to 'order' modules required for the examples.
        base_params = {
            "project": "Project Name or UUID",
            "offering": "Offering Name or UUID",
        }

        # Step 2: Call the shared example builder from the base class.
        examples = super()._build_examples_from_schema(
            module_config=module_config,
            module_name=module_name,
            collection_namespace=collection_namespace,
            collection_name=collection_name,
            schema_parser=schema_parser,
            create_schema=attributes_schema,
            base_params=base_params,
            delete_identifier_param="name",  # The resource is identified by 'name' for deletion
        )

        # Step 3: (Optional) Add any plugin-specific examples, like 'update'.
        if module_config.update_op and module_config.update_check_fields:
            update_example_params = {
                "state": "present",
                "name": schema_parser._generate_sample_value(
                    "name", {}, module_config.resource_type
                ),
                "project": "Project Name or UUID",
                "access_token": "b83557fd8e2066e98f27dee8f3b3433cdc4183ce",
                "api_url": "https://waldur.example.com",
            }
            # Add the first updatable field to the example.
            field_to_update = module_config.update_check_fields[0]
            update_example_params[field_to_update] = f"An updated {field_to_update}"

            fqcn = f"{collection_namespace}.{collection_name}.{module_name}"
            examples.insert(
                1,
                {
                    "name": f"Update an existing {module_config.resource_type}",
                    "hosts": "localhost",
                    "tasks": [
                        {
                            "name": f"Update the {field_to_update} of a {module_config.resource_type}",
                            fqcn: update_example_params,
                        }
                    ],
                },
            )

        return examples

    def _create_param_config_from_schema(
        self,
        name: str,
        prop: Dict[str, Any],
        required_list: List[str],
        api_parser: ApiSpecParser,
        module_config: OrderModuleConfig,
    ) -> ParameterConfig:
        """
        Recursively creates a ParameterConfig object from a name and a schema property.
        """
        # Determine the type. If there's a $ref, it's an object to be resolved later.
        prop_type = prop.get("type")
        if not prop_type and "$ref" in prop:
            prop_type = "object"
        elif not prop_type:
            prop_type = "string"  # A safe default

        # Handle nested properties
        sub_properties = []
        if "properties" in prop:
            nested_required = prop.get("required", [])
            for sub_name, sub_prop in prop.get("properties", {}).items():
                if sub_prop.get("readOnly"):
                    continue
                # Recursive call for nested properties
                sub_properties.append(
                    self._create_param_config_from_schema(
                        sub_name, sub_prop, nested_required, api_parser, module_config
                    )
                )

        # Handle nested items in an array
        items_config = None
        if "items" in prop and isinstance(prop.get("items"), dict):
            # The name for an 'items' block is internal; it's not user-facing.
            # We use a placeholder name.
            items_config = self._create_param_config_from_schema(
                name="_items_definition",
                prop=prop["items"],
                required_list=[],  # 'required' is not meaningful inside an array item
                api_parser=api_parser,
                module_config=module_config,
            )

        choices = self._extract_choices_from_prop(prop, api_parser)
        is_resolved = name in module_config.resolvers

        return ParameterConfig(
            name=name,
            type=prop_type,
            format=prop.get("format"),
            required=(name in required_list),
            description=self._get_prop_description(name, prop, module_config),
            is_resolved=is_resolved,
            choices=choices if choices else [],
            ref=prop.get("$ref"),  # The ref is at the top level of the property
            properties=sub_properties,
            items=items_config,
        )

    def _get_prop_description(
        self, name: str, prop: Dict[str, Any], module_config
    ) -> str:
        description = prop.get("description", "")
        display_name = name.replace("_", " ")
        # Convert common abbreviations to uppercase
        display_name = re.sub(
            r"\b(ssh|ip|id|url|cpu|ram|vpn|uuid|dns|cidr)\b",
            lambda m: m.group(1).upper(),
            display_name,
            flags=re.IGNORECASE,
        )

        if not description:
            if name in module_config.resolvers:
                description = f"The name or UUID of the {display_name}."
            elif prop.get("format") == "uri":
                description = f"{capitalize_first(display_name)} URL"
            elif prop.get("type") == "array":
                description = f"A list of {display_name} items."
            else:
                description = capitalize_first(display_name)
        return description

    def _infer_offering_params(
        self, module_config: OrderModuleConfig, api_parser: ApiSpecParser
    ) -> list[ParameterConfig]:
        """Infers attribute parameters from the OpenAPI schema based on offering_type."""
        if not module_config.offering_type:
            return []

        schema_name = (
            f"{module_config.offering_type.replace('.', '')}CreateOrderAttributes"
        )
        schema_ref = f"#/components/schemas/{schema_name}"

        try:
            schema = api_parser.get_schema_by_ref(schema_ref)
        except ValueError:
            # Handle error as before
            return []

        if not schema or "properties" not in schema:
            return []

        inferred_params = []
        required_fields = schema.get("required", [])

        # The loop is now much simpler and delegates the complex creation logic
        for name, prop in schema.get("properties", {}).items():
            if prop.get("readOnly", False):
                continue

            param = self._create_param_config_from_schema(
                name=name,
                prop=prop,
                required_list=required_fields,
                api_parser=api_parser,
                module_config=module_config,
            )
            inferred_params.append(param)

        return inferred_params

    def _validate_resolvers(
        self,
        resolvers: dict[str, OrderModuleResolver],
        api_parser: ApiSpecParser,
        module_key: str,
    ):
        """
        Validates the resolver configurations, including the new `filter_by` dependencies.
        """
        for resolver_name, resolver_config in resolvers.items():
            if not resolver_config.filter_by:
                continue

            # Get the set of valid query parameters for the list operation.
            list_op_id = resolver_config.list_operation.operation_id
            valid_query_params = api_parser.get_query_parameters_for_operation(
                list_op_id
            )

            for filter_config in resolver_config.filter_by:
                target_key = filter_config.target_key
                if target_key not in valid_query_params:
                    # Throw a specific, helpful error if the target_key is invalid.
                    raise ValueError(
                        f"Validation Error in module '{module_key}', resolver '{resolver_name}': "
                        f"The specified target_key '{target_key}' is not a valid filter parameter for the list operation '{list_op_id}'. "
                        f"Available filters are: {sorted(list(valid_query_params))}"
                    )

    def _parse_configuration(self, module_key, raw_config, api_parser):
        raw_config.setdefault("resolvers", {})
        raw_config["resolvers"]["offering"] = {
            "list": "marketplace_public_offerings_list",
            "retrieve": "marketplace_public_offerings_retrieve",
        }
        raw_config["resolvers"]["project"] = {
            "list": "projects_list",
            "retrieve": "projects_retrieve",
        }
        raw_config["existence_check_op"] = api_parser.get_operation(
            raw_config["existence_check_op"]
        )
        if "update_op" in raw_config:
            raw_config["update_op"] = api_parser.get_operation(raw_config["update_op"])

        parsed_resolvers = {}
        for name, resolver_conf in raw_config.get("resolvers", {}).items():
            resolver_conf["list_operation"] = api_parser.get_operation(
                resolver_conf["list"]
            )
            resolver_conf["retrieve_operation"] = api_parser.get_operation(
                resolver_conf["retrieve"]
            )
            parsed_resolvers[name] = OrderModuleResolver(**resolver_conf)

        self._validate_resolvers(parsed_resolvers, api_parser, module_key)

        raw_config["resolvers"] = parsed_resolvers

        module_config = OrderModuleConfig(**raw_config)

        # Infer params from offering_type and merge them into the module_config
        inferred_params = self._infer_offering_params(module_config, api_parser)
        final_params_dict = {p.name: p for p in inferred_params}
        for manual_param in module_config.attribute_params:
            final_params_dict[manual_param.name] = manual_param
        module_config.attribute_params = list(final_params_dict.values())
        return module_config
