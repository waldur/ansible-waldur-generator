from abc import ABC, abstractmethod
import os
import sys
from typing import Dict, Any

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.models import GenerationContext
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator


class BasePlugin(ABC):
    """
    The interface that all generator plugins must implement.
    """

    @abstractmethod
    def get_type_name(self) -> str: ...

    @abstractmethod
    def generate(
        self,
        module_key: str,
        raw_config: Dict[str, Any],
        api_parser: ApiSpecParser,
        collection_namespace: str,
        collection_name: str,
        return_generator: ReturnBlockGenerator,
    ) -> GenerationContext: ...

    def _build_argument_spec(self, parameters: Dict[str, Any]) -> dict:
        """Constructs the full 'argument_spec' dictionary for AnsibleModule."""
        spec = {}
        for name, opts in parameters.items():
            param_spec = {"type": opts["type"], "required": opts.get("required", False)}
            if "choices" in opts and opts["choices"] is not None:
                param_spec["choices"] = opts["choices"]
            spec[name] = param_spec
        return spec

    def _build_documentation(
        self,
        module_name: str,
        description: str | None,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        processed_description = description or f"Manage {module_name}"
        return {
            "module": module_name,
            "short_description": processed_description,
            "description": [processed_description],
            "author": "Waldur Team",
            "options": parameters,
            "requirements": ["python >= 3.11"],
        }

    def _build_examples_from_schema(
        self,
        module_config: Any,
        module_name: str,
        collection_namespace: str,
        collection_name: str,
        schema_parser: ReturnBlockGenerator,
        create_schema: Dict[str, Any],
        # Base parameters required for all examples
        base_params: Dict[str, Any],
        # Identifier for the resource in 'delete' examples
        delete_identifier_param: str = "name",
    ) -> list[dict]:
        """
        Builds realistic EXAMPLES using a hybrid of schema-inferred data
        and context-aware placeholders for resolved parameters. This is a
        shared helper for all plugins.
        """
        fqcn = f"{collection_namespace}.{collection_name}.{module_name}"

        # --- Create Example ---
        create_params = {
            "state": "present",
            "access_token": "b83557fd8e2066e98f27dee8f3b3433cdc4183ce",
            "api_url": "https://waldur.example.com",
            **base_params,
        }

        # Step 1: Generate the base payload from the provided schema.
        inferred_payload = schema_parser.generate_example_from_schema(
            create_schema, module_config.resource_type
        )
        create_params.update(inferred_payload)

        # Step 2: Post-process to add instructive placeholders for resolved parameters.
        # This handles nested path parameters (e.g., 'tenant' for crud).
        path_param_maps = getattr(module_config, "path_param_maps", {})
        for _, ansible_param in path_param_maps.get("create", {}).items():
            create_params[ansible_param] = (
                f"{ansible_param.replace('_', ' ').capitalize()} name or UUID"
            )

        # This handles any resolved parameters in the request body (common to all plugins).
        for resolver_name in getattr(module_config, "resolvers", {}).keys():
            if resolver_name in create_params:
                create_params[resolver_name] = (
                    f"{resolver_name.replace('_', ' ').capitalize()} name or UUID"
                )

        # --- Delete Example ---
        delete_params = {
            "state": "absent",
            delete_identifier_param: schema_parser._generate_sample_value(
                delete_identifier_param, {}, module_config.resource_type
            ),
            "access_token": "b83557fd8e2066e98f27dee8f3b3433cdc4183ce",
            "api_url": "https://waldur.example.com",
            **base_params,
        }

        return [
            {
                "name": f"Create a new {module_config.resource_type}",
                "hosts": "localhost",
                "tasks": [
                    {"name": f"Add {module_config.resource_type}", fqcn: create_params}
                ],
            },
            {
                "name": f"Remove an existing {module_config.resource_type}",
                "hosts": "localhost",
                "tasks": [
                    {
                        "name": f"Remove {module_config.resource_type}",
                        fqcn: delete_params,
                    }
                ],
            },
        ]

    def get_runner_path(self) -> str | None:
        module = sys.modules[self.__class__.__module__]
        if not module.__file__:
            return None
        plugin_dir = os.path.dirname(module.__file__)
        runner_path = os.path.join(plugin_dir, "runner.py")
        return runner_path if os.path.exists(runner_path) else None

    def _extract_choices_from_prop(
        self, prop_schema: Dict[str, Any], api_parser: ApiSpecParser
    ) -> list[str] | None:
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
