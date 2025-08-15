from typing import Dict, Any, List

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator
from ansible_waldur_generator.models import (
    GenerationContext,
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

BASE_SPEC = {
    **AUTH_OPTIONS,  # Include standard auth options
    "state": {
        "description": "Should the resource be present or absent.",
        "choices": ["present", "absent"],
        "default": "present",
        "type": "str",
    },
}


class CrudPlugin(BasePlugin):
    def get_type_name(self) -> str:
        return "crud"

    def _build_return_block(
        self, module_config: CrudModuleConfig, return_generator: ReturnBlockGenerator
    ) -> Dict[str, Any] | None:
        # We generate it from the 'create' operation's success response,
        # as that typically returns the full resource object.
        return_block = None
        create_op_spec = module_config.create_section.raw_spec
        return_content = return_generator.generate_for_operation(create_op_spec)

        # Structure it for Ansible's RETURN docs
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

    def _build_runner_context(self, module_config: CrudModuleConfig) -> Dict[str, Any]:
        """
        Builds the runner_context as a dictionary.
        """
        conf = module_config

        resolvers_data = {}
        for name, resolver in conf.resolvers.items():
            resolvers_data[name] = {
                "url": resolver.list_operation.path if resolver.list_operation else "",
                "error_message": resolver.error_message,
            }

        return {
            "resource_type": conf.resource_type,
            "api_path": conf.create_section.path if conf.create_section else "",
            "model_param_names": self._get_model_param_names(module_config),
            "resolvers": resolvers_data,
        }

    def _get_model_param_names(self, module_config: CrudModuleConfig) -> List[str]:
        """Helper to get a list of parameter names from the model schema."""
        if not module_config.create_section:
            return []
        schema = module_config.create_section.model_schema
        if not schema or "properties" not in schema:
            return []
        return [
            name
            for name, prop in schema["properties"].items()
            if not prop.get("readOnly", False)
        ]

    def _extract_choices_from_prop(
        self, prop_schema: Dict[str, Any], api_parser: ApiSpecParser
    ) -> List[str] | None:
        """
        Extracts a list of enum choices from a property schema.
        It correctly handles both direct enums and 'oneOf' constructs with $refs.
        """
        choices = []
        if "enum" in prop_schema:
            choices.extend(prop_schema["enum"])

        elif "oneOf" in prop_schema:
            for sub_ref in prop_schema["oneOf"]:
                if "$ref" in sub_ref:
                    try:
                        # Correctly resolve the reference against the full API spec.
                        target_schema = api_parser.get_schema_by_ref(sub_ref["$ref"])
                        if "enum" in target_schema:
                            choices.extend(target_schema["enum"])
                    except (ValueError, KeyError) as e:
                        print(
                            f"Could not resolve $ref '{sub_ref['$ref']}' for enum: {e}"
                        )

        # Filter out any null/None values and return the list, or None if empty.
        return [c for c in choices if c is not None] or None

    def _build_parameters(
        self, module_config: CrudModuleConfig, api_parser: ApiSpecParser
    ) -> AnsibleModuleParams:
        """
        Creates the complete dictionary of Ansible module parameters. This is a critical
        method that infers parameters from the create operation's schema, validates them,
        and combines them with any explicitly defined parameters.
        """
        params: AnsibleModuleParams = {**BASE_SPEC}
        conf = module_config

        # 1. Add explicitly defined parameters first (e.g., from existence_check).
        for p in conf.check_section_config.get("params", []):
            p["type"] = OPENAPI_TO_ANSIBLE_TYPE_MAP.get(p.get("type", "str"), "str")
            params[p["name"]] = p

        # 2. Add parameters inferred from the 'create' operation's request body schema.
        if conf.create_section:
            schema = conf.create_section.model_schema
            if not schema:
                return params

            required_fields = schema.get("required", [])
            for name, prop in schema.get("properties", {}).items():
                # Skip fields that are read-only (server-generated) or already defined.
                if prop.get("readOnly", False):
                    continue

                is_resolved = name in conf.resolvers
                description = prop.get(
                    "description", capitalize_first(name.replace("_", " "))
                )

                if (
                    prop.get("format") == "uri"
                    and not is_resolved
                    and name not in conf.skip_resolver_check
                ):
                    print(
                        f"Module '{conf.resource_type}': Param '{name}' has 'format: uri' but no resolver is defined and is not skipped."
                    )

                if is_resolved:
                    description = f"The name or UUID of the {name}. {description}"

                # Extract enum choices, if any.
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
        return params

    def _build_examples(
        self,
        module_config: CrudModuleConfig,
        module_name: str,
        parameters: AnsibleModuleParams,
        collection_namespace: str,
        collection_name: str,
    ) -> List[Dict[str, Any]]:
        """Builds the EXAMPLES block as a list of Python dictionaries."""

        def get_example_params(param_names, extra_params=None):
            """Internal helper to build the parameter dict for a task."""
            params = {
                "access_token": "b83557fd8e2066e98f27dee8f3b3433cdc4183ce",
                "api_url": "https://waldur.example.com:8000/api",
            }
            if extra_params:
                params.update(extra_params)
            for p_name in param_names:
                info = parameters.get(p_name, {})
                if info.get("is_resolved"):
                    value = f"{p_name.capitalize()} Name or UUID"
                elif "homepage" in p_name:
                    value = "https://example.com/project"
                elif "name" in p_name:
                    value = f"My Awesome {module_config.resource_type.capitalize()}"
                elif "description" in p_name:
                    value = "Created with Ansible"
                elif info.get("choices"):
                    choice = info["choices"][0]
                    value = choice if choice is not None else ""
                else:
                    value = "some_value"
                params[p_name] = value
            return params

        create_names = [
            name for name, opts in parameters.items() if opts.get("required")
        ]
        delete_names = [
            p["name"] for p in module_config.check_section_config.get("params", [])
        ]
        fqcn = f"{collection_namespace}.{collection_name}.{module_name}"

        return [
            {
                "name": f"Create a new {module_config.resource_type}.",
                "hosts": "localhost",
                "tasks": [
                    {
                        "name": f"Add {module_config.resource_type}",
                        fqcn: get_example_params(create_names, {"state": "present"}),
                    }
                ],
            },
            {
                "name": f"Remove an existing {module_config.resource_type}.",
                "hosts": "localhost",
                "tasks": [
                    {
                        "name": f"Remove {module_config.resource_type}",
                        fqcn: get_example_params(delete_names, {"state": "absent"}),
                    }
                ],
            },
        ]

    def _validate_config(self, config: Dict[str, Any]):
        # Check required operations exist
        operations = config.get("operations", {})
        required = ["list", "create", "destroy"]
        missing = [op for op in required if op not in operations]
        if missing:
            raise ValueError(f"Missing operations: {missing}")

        # Check resolvers have required fields
        for name, resolver in config.get("resolvers", {}).items():
            if "list" not in resolver or "retrieve" not in resolver:
                raise ValueError(f"Resolver '{name}' missing list/retrieve operations")

    def generate(
        self,
        module_key: str,
        raw_config: Dict[str, Any],
        api_parser: ApiSpecParser,
        collection_namespace: str,
        collection_name: str,
        return_generator: ReturnBlockGenerator,
    ) -> GenerationContext:
        self._validate_config(raw_config)
        operations = raw_config["operations"]
        raw_config["check_section"] = api_parser.get_operation(operations["list"])
        raw_config["create_section"] = api_parser.get_operation(operations["create"])
        raw_config["destroy_section"] = api_parser.get_operation(operations["destroy"])

        for name, resolver_conf in raw_config.get("resolvers", {}).items():
            resolver_conf["list_operation"] = api_parser.get_operation(
                resolver_conf["list"]
            )
            resolver_conf["retrieve_operation"] = api_parser.get_operation(
                resolver_conf["retrieve"]
            )

        module_config = CrudModuleConfig(**raw_config)

        parameters = self._build_parameters(module_config, api_parser)
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
            return_block=return_block or {},
            runner_context=runner_context,
        )
