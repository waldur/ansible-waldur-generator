from typing import Dict, Any, List

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator
from ansible_waldur_generator.models import GenerationContext, AnsibleModuleParams
from ansible_waldur_generator.helpers import (
    AUTH_OPTIONS,
    OPENAPI_TO_ANSIBLE_TYPE_MAP,
)
from ansible_waldur_generator.interfaces.plugin import BasePlugin
from ansible_waldur_generator.plugins.order.config import (
    AttributeParam,
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

    def _build_parameters(
        self, module_config: OrderModuleConfig
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
            param_name = p_conf.name
            param_type = OPENAPI_TO_ANSIBLE_TYPE_MAP.get(p_conf.type, "str")
            description = p_conf.description or ""
            if p_conf.is_resolved:
                description = f"The name or UUID of the {param_name}. {description}"

            params[param_name] = {
                "type": param_type,
                "required": p_conf.required,
                "description": description.strip(),
            }
            if p_conf.choices:
                params[param_name]["choices"] = p_conf.choices

        return params

    def _build_runner_context(self, module_config: OrderModuleConfig) -> Dict[str, Any]:
        resolvers_data = {}
        for name, resolver in module_config.resolvers.items():
            resolvers_data[name] = {
                "url": resolver.list_operation.path if resolver.list_operation else "",
                "error_message": resolver.error_message,
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

    def _build_examples(
        self,
        module_config: OrderModuleConfig,
        module_name: str,
        parameters: AnsibleModuleParams,
        collection_namespace: str,
        collection_name: str,
    ) -> List[Dict[str, Any]]:
        def get_example_params(param_names, extra_params=None):
            params = {
                "access_token": "b83557fd8e2066e98f27dee8f3b3433cdc4183ce",
                "api_url": "https://waldur.example.com/api",
            }
            if extra_params:
                params.update(extra_params)

            for p_name in param_names:
                info = parameters.get(p_name, {})
                value: Any = None
                if "project" in p_name:
                    value = "Cloud Project"
                elif "offering" in p_name:
                    value = "Standard Volume Offering"
                elif "name" in p_name:
                    value = (
                        f"My-Awesome-{module_config.resource_type.replace(' ', '-')}"
                    )
                elif "size" in p_name:
                    value = 10
                elif info.get("choices"):
                    value = info["choices"][0]
                else:
                    value = "some_value"
                params[p_name] = value
            return params

        create_param_names = [
            name for name, opts in parameters.items() if opts.get("required")
        ]

        update_example_params = {
            "name": f"My-Awesome-{module_config.resource_type.replace(' ', '-')}",
            "project": "Cloud Project",
            "state": "present",
            "description": "A new updated description for the resource.",
            "access_token": "b83557fd8e2066e98f27dee8f3b3433cdc4183ce",
            "api_url": "https://waldur.example.com/api",
        }

        fqcn = f"{collection_namespace}.{collection_name}.{module_name}"

        examples = [
            {
                "name": f"Create a new {module_config.resource_type}",
                "hosts": "localhost",
                "tasks": [
                    {
                        "name": f"Add {module_config.resource_type}",
                        fqcn: get_example_params(
                            create_param_names, {"state": "present"}
                        ),
                    }
                ],
            },
            {
                "name": f"Update an existing {module_config.resource_type}",
                "hosts": "localhost",
                "tasks": [
                    {
                        "name": f"Update the description of a {module_config.resource_type}",
                        fqcn: update_example_params,
                    }
                ],
            },
            {
                "name": f"Remove an existing {module_config.resource_type}",
                "hosts": "localhost",
                "tasks": [
                    {
                        "name": f"Remove {module_config.resource_type}",
                        fqcn: {
                            "name": f"My-Awesome-{module_config.resource_type.replace(' ', '-')}",
                            "project": "Cloud Project",
                            "state": "absent",
                            "access_token": "b83557fd8e2066e98f27dee8f3b3433cdc4183ce",
                            "api_url": "https://waldur.example.com/api",
                        },
                    }
                ],
            },
        ]

        if not module_config.update_op:
            examples.pop(1)

        return examples

    def _infer_attribute_params(
        self, module_config: OrderModuleConfig, api_parser: ApiSpecParser
    ) -> list[AttributeParam]:
        """Infers attribute parameters from the OpenAPI schema based on offering_type."""
        if not module_config.offering_type:
            return []

        schema_name = (
            f"{module_config.offering_type.replace('.', '')}CreateOrderAttributes"
        )
        schema_ref = f"#/components/schemas/{schema_name}"

        try:
            schema = api_parser.get_schema_by_ref(schema_ref)
        except ValueError as e:
            print(
                f"Warning for offering_type '{module_config.offering_type}': "
                f"Could not resolve schema ref '{schema_ref}'. No attributes will be inferred. Details: {e}"
            )
            return []
        if not schema or "properties" not in schema:
            return []

        inferred_params = []
        required_fields = schema.get("required", [])

        for name, prop in schema.get("properties", {}).items():
            if prop.get("readOnly", False):
                continue

            choices = self._extract_choices_from_prop(prop, api_parser)

            # For `is_resolved`, we check if a resolver is defined for this parameter name.
            # This allows auto-detection if the user adds a resolver for an inferred param.
            is_resolved = name in module_config.resolvers

            param = AttributeParam(
                name=name,
                type=prop.get("type", "string"),
                required=name in required_fields,
                description=prop.get("description", "").strip(),
                is_resolved=is_resolved,
                choices=choices if choices else [],
            )
            inferred_params.append(param)

        return inferred_params

    def generate(
        self,
        module_key: str,
        raw_config: Dict[str, Any],
        api_parser: ApiSpecParser,
        collection_namespace: str,
        collection_name: str,
        return_generator: ReturnBlockGenerator,
    ) -> GenerationContext:
        raw_config.setdefault("resolvers", {})
        raw_config["resolvers"]["offering"] = {
            "list": "/api/marketplace-public-offerings/",
            "retrieve": "/api/marketplace-public-offerings/{uuid}/",
        }
        raw_config["resolvers"]["project"] = {
            "list": "/api/projects/",
            "retrieve": "/api/projects/{uuid}/",
        }
        raw_config["existence_check_op"] = api_parser.get_operation(
            raw_config["existence_check_op"]
        )
        if "update_op" in raw_config:
            raw_config["update_op"] = api_parser.get_operation(raw_config["update_op"])

        for name, resolver_conf in raw_config.get("resolvers", {}).items():
            resolver_conf["list_operation"] = api_parser.get_operation(
                resolver_conf["list"]
            )
            resolver_conf["retrieve_operation"] = api_parser.get_operation(
                resolver_conf["retrieve"]
            )

        module_config = OrderModuleConfig(**raw_config)

        # Infer params from offering_type and merge them into the module_config
        inferred_params = self._infer_attribute_params(module_config, api_parser)
        final_params_dict = {p.name: p for p in inferred_params}
        for manual_param in module_config.attribute_params:
            final_params_dict[manual_param.name] = manual_param
        module_config.attribute_params = list(final_params_dict.values())

        parameters = self._build_parameters(module_config)
        return_block = self._build_return_block(module_config, return_generator)
        examples = self._build_examples(
            module_config,
            module_key,
            parameters,
            collection_namespace,
            collection_name,
        )
        runner_context = self._build_runner_context(module_config)

        return GenerationContext(
            argument_spec=self._build_argument_spec(parameters),
            module_filename=f"{module_key}.py",
            documentation=self._build_documentation(
                module_key, module_config.description, parameters
            ),
            examples=examples,
            return_block=return_block,
            runner_context=runner_context,
        )
