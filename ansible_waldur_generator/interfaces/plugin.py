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
