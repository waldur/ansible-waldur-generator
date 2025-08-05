"""
Builds the final CrudGenerationContext object required by the Jinja2 template.

This class is the "workhorse" that transforms a validated ModuleConfig object
into all the Ansible-specific data structures, such as module parameters,
import lists, and documentation blocks.
"""

import yaml
from typing import Dict, List, Any

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.helpers import (
    AUTH_OPTIONS,
    OPENAPI_TO_ANSIBLE_TYPE_MAP,
    ValidationErrorCollector,
)
from ansible_waldur_generator.interfaces.builder import BaseContextBuilder
from ansible_waldur_generator.models import (
    AnsibleModuleParams,
    BaseGenerationContext,
)
from ansible_waldur_generator.plugins.crud.config import CrudModuleConfig
from ansible_waldur_generator.plugins.crud.context import CrudRunnerContext


class CrudContextBuilder(BaseContextBuilder):
    def __init__(
        self,
        module_config: CrudModuleConfig,
        api_parser: ApiSpecParser,
        collector: ValidationErrorCollector,
    ):
        """
        Initializes the builder.

        Args:
            module_config (ModuleConfig): The validated configuration for one module.
            api_parser (ApiSpecParser): The OpenAPI specification parser, needed for resolving refs.
            collector: The validation error collector instance.
        """
        self.module_config = module_config
        self.api_parser = api_parser
        self.collector = collector

    def build(self) -> BaseGenerationContext:
        """
        Main entry point to build the full, flattened context for a single module.
        It orchestrates the creation of all necessary data for the template.
        """
        module_name = f"waldur_{self.module_config.module_key}"

        # 1. Build the dictionary of Ansible parameters for the module.
        parameters = self._build_parameters()

        # 2. Collect all unique SDK imports needed for the module's logic.
        sdk_imports = self._collect_imports()

        # 3. Build the data structures for documentation and examples.
        doc_data = self._build_documentation_data(module_name, parameters)
        examples_data = self._build_examples_data(module_name, parameters)

        # 4. Convert these data structures into formatted YAML strings.
        # This separates data generation from presentation, ensuring valid YAML.

        doc_yaml = yaml.dump(doc_data, default_flow_style=False, sort_keys=False)
        examples_yaml = yaml.dump(
            examples_data, default_flow_style=False, sort_keys=False
        )

        # 5. Return context object, ready for rendering.
        return BaseGenerationContext(
            description=self.module_config.description,
            module_name=module_name,
            parameters=parameters,
            sdk_imports=sdk_imports,
            documentation_yaml=doc_yaml,
            examples_yaml=examples_yaml,
            runner_context=CrudRunnerContext(
                resource_type=self.module_config.resource_type,
                existence_check_func=self.module_config.existence_check.sdk_op.sdk_function,
                present_create_func=self.module_config.present_create.sdk_op.sdk_function,
                present_create_model_class=self.module_config.present_create.sdk_op.model_class,
                absent_destroy_func=self.module_config.absent_destroy.sdk_op.sdk_function,
                absent_destroy_path_param=self.module_config.absent_destroy.config.get(
                    "path_param_field", "uuid"
                ),
                model_param_names=self._get_model_param_names(),
                resolvers=self._build_flat_resolvers(),
            ),
        )

    def _get_model_param_names(self) -> List[str]:
        """Helper to get a list of parameter names from the model schema."""
        schema = self.module_config.present_create.sdk_op.model_schema
        if not schema or "properties" not in schema:
            return []
        return [
            name
            for name, prop in schema["properties"].items()
            if not prop.get("readOnly", False)
        ]

    def _extract_choices_from_prop(self, prop_schema: Dict[str, Any]) -> List[str]:
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
                        target_schema = self.api_parser.get_schema_by_ref(
                            sub_ref["$ref"]
                        )
                        if "enum" in target_schema:
                            choices.extend(target_schema["enum"])
                    except (ValueError, KeyError) as e:
                        self.collector.add_error(
                            f"Could not resolve $ref '{sub_ref['$ref']}' for enum: {e}"
                        )

        # Filter out any null/None values and return the list, or None if empty.
        return [c for c in choices if c is not None] or None

    def _build_parameters(self) -> AnsibleModuleParams:
        """
        Creates the complete dictionary of Ansible module parameters. This is a critical
        method that infers parameters from the create operation's schema, validates them,
        and combines them with any explicitly defined parameters.
        """
        params = {}
        conf = self.module_config

        # 1. Add explicitly defined parameters first (e.g., from existence_check).
        for p in conf.existence_check.config.get("params", []):
            p["type"] = OPENAPI_TO_ANSIBLE_TYPE_MAP.get(p.get("type", "str"), "str")
            params[p["name"]] = p

        # 2. Add parameters inferred from the 'create' operation's request body schema.
        schema = conf.present_create.sdk_op.model_schema
        if schema:
            required_fields = schema.get("required", [])
            for name, prop in schema.get("properties", {}).items():
                # Skip fields that are read-only (server-generated) or already defined.
                if prop.get("readOnly", False):
                    continue
                if name in params:
                    continue

                is_resolved = name in conf.resolvers
                description = prop.get("description", "")

                # Validate that any parameter expecting a URI is either resolved or explicitly skipped.
                if (
                    prop.get("format") == "uri"
                    and not is_resolved
                    and name not in conf.skip_resolver_check
                ):
                    self.collector.add_error(
                        f"Module '{conf.module_key}': Param '{name}' has 'format: uri' but no resolver is defined and is not skipped."
                    )

                if is_resolved:
                    description = f"The name or UUID of the {name}. {description}"

                # Extract enum choices, if any.
                choices = self._extract_choices_from_prop(prop)

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

    def _collect_imports(self) -> List[Dict[str, str]]:
        """Collects all unique SDK module/function/class pairs needed for the module."""
        imports = set()
        # Gather all SdkOperation objects from the config.
        operations = [
            self.module_config.existence_check.sdk_op,
            self.module_config.present_create.sdk_op,
            self.module_config.absent_destroy.sdk_op,
        ]
        for resolver in self.module_config.resolvers.values():
            operations.append(resolver.list_op)
            operations.append(resolver.retrieve_op)

        for op in operations:
            if not op:
                continue
            # Add the function import
            imports.add((op.sdk_module, op.sdk_function))
            # Add the model class import if it exists
            if op.model_module and op.model_class:
                imports.add((op.model_module, op.model_class))

        return [
            {"module": mod.replace("-", "_"), "function": func}
            for mod, func in sorted(list(imports))
        ]

    def _build_flat_resolvers(self) -> Dict[str, Dict[str, Any]]:
        """Creates a simple, flattened resolver dictionary for the template."""
        flat_resolvers = {}
        for name, resolver in self.module_config.resolvers.items():
            flat_resolvers[name] = {
                "list_func": resolver.list_op.sdk_function,
                "retrieve_func": resolver.retrieve_op.sdk_function,
                "error_message": resolver.error_message,
            }
        return flat_resolvers

    def _build_documentation_data(
        self, module_name: str, parameters: AnsibleModuleParams
    ) -> Dict[str, Any]:
        """Builds the DOCUMENTATION block as a Python dictionary."""
        doc = {
            "module": module_name,
            "short_description": self.module_config.description,
            "version_added": "0.1",
            "description": [self.module_config.description],
            "requirements": ["python = 3.11", "waldur-api-client"],
            "options": {},
        }
        std_opts = {
            **AUTH_OPTIONS,
            "state": {
                "description": "Should the resource be present or absent.",
                "choices": ["present", "absent"],
                "default": "present",
                "type": "str",
            },
        }
        doc["options"].update(std_opts)

        for name, opts in parameters.items():
            # Filter for keys relevant to documentation and ensure 'required' is always present.
            doc_data = {
                k: v
                for k, v in opts.items()
                if k in ["description", "required", "type", "choices"] and v is not None
            }
            if "required" not in doc_data:
                doc_data["required"] = False
            doc["options"][name] = doc_data
        return doc

    def _build_examples_data(
        self, module_name: str, parameters: AnsibleModuleParams
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
                    value = (
                        f"My Awesome {self.module_config.resource_type.capitalize()}"
                    )
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
            p["name"]
            for p in self.module_config.existence_check.config.get("params", [])
        ]

        return [
            {
                "name": f"Create a new {self.module_config.resource_type}.",
                "hosts": "localhost",
                "tasks": [
                    {
                        "name": f"Add {self.module_config.resource_type}",
                        module_name: get_example_params(
                            create_names, {"state": "present"}
                        ),
                    }
                ],
            },
            {
                "name": f"Remove an existing {self.module_config.resource_type}.",
                "hosts": "localhost",
                "tasks": [
                    {
                        "name": f"Remove {self.module_config.resource_type}",
                        module_name: get_example_params(
                            delete_names, {"state": "absent"}
                        ),
                    }
                ],
            },
        ]
