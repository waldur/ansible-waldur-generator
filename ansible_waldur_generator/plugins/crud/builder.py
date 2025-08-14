"""
Builds the final CrudGenerationContext object required by the template.

This class is the "workhorse" that transforms a validated ModuleConfig object
into all the Ansible-specific data structures, such as module parameters,
import lists, and documentation blocks.
"""

from typing import Dict, List, Any

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.helpers import (
    AUTH_OPTIONS,
    OPENAPI_TO_ANSIBLE_TYPE_MAP,
    ValidationErrorCollector,
    capitalize_first,
)
from ansible_waldur_generator.interfaces.builder import BaseContextBuilder
from ansible_waldur_generator.models import (
    AnsibleModuleParams,
)
from ansible_waldur_generator.plugins.crud.config import CrudModuleConfig


BASE_SPEC = {
    **AUTH_OPTIONS,  # Include standard auth options
    "state": {
        "description": "Should the resource be present or absent.",
        "choices": ["present", "absent"],
        "default": "present",
        "type": "str",
    },
}


class CrudContextBuilder(BaseContextBuilder):
    def __init__(
        self,
        module_config: CrudModuleConfig,
        api_parser: ApiSpecParser,
        collector: ValidationErrorCollector,
    ):
        super().__init__(module_config, api_parser, collector)
        # Ensure the module_config is of the correct type.
        self.module_config = module_config

    def _build_return_block(self) -> Dict[str, Any]:
        # We generate it from the 'create' operation's success response,
        # as that typically returns the full resource object.
        return_block = None
        create_op_spec = self.module_config.create_section.raw_spec
        return_content = self.return_generator.generate_for_operation(create_op_spec)

        # Structure it for Ansible's RETURN docs
        if return_content:
            return_block = {
                "resource": {
                    "description": f"The state of the {self.module_config.resource_type} after the operation.",
                    "type": "dict",
                    "returned": "on success",
                    "contains": return_content,
                }
            }
        return return_block

    def _build_runner_context(self) -> Dict[str, Any]:
        """
        Builds the runner_context as a dictionary.
        """
        conf = self.module_config

        resolvers_data = {}
        for name, resolver in conf.resolvers.items():
            resolvers_data[name] = {
                "url": resolver.list_op.path if resolver.list_op else "",
                "error_message": resolver.error_message,
            }

        return {
            "resource_type": conf.resource_type,
            "api_path": conf.create_section.path if conf.create_section else "",
            "model_param_names": self._get_model_param_names(),
            "resolvers": resolvers_data,
        }

    def _get_model_param_names(self) -> List[str]:
        """Helper to get a list of parameter names from the model schema."""
        if not self.module_config.create_section:
            return []
        schema = self.module_config.create_section.model_schema
        if not schema or "properties" not in schema:
            return []
        return [
            name
            for name, prop in schema["properties"].items()
            if not prop.get("readOnly", False)
        ]

    def _extract_choices_from_prop(
        self, prop_schema: Dict[str, Any]
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
        params: AnsibleModuleParams = {**BASE_SPEC}
        conf = self.module_config

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

    def _build_examples(
        self,
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
            p["name"] for p in self.module_config.check_section_config.get("params", [])
        ]
        fqcn = f"{collection_namespace}.{collection_name}.{module_name}"

        return [
            {
                "name": f"Create a new {self.module_config.resource_type}.",
                "hosts": "localhost",
                "tasks": [
                    {
                        "name": f"Add {self.module_config.resource_type}",
                        fqcn: get_example_params(create_names, {"state": "present"}),
                    }
                ],
            },
            {
                "name": f"Remove an existing {self.module_config.resource_type}.",
                "hosts": "localhost",
                "tasks": [
                    {
                        "name": f"Remove {self.module_config.resource_type}",
                        fqcn: get_example_params(delete_names, {"state": "absent"}),
                    }
                ],
            },
        ]
