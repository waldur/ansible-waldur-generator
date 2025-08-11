from abc import ABC, abstractmethod
from typing import Any

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.helpers import AUTH_OPTIONS, ValidationErrorCollector
from ansible_waldur_generator.interfaces.config import BaseModuleConfig
from ansible_waldur_generator.models import AnsibleModuleParams, BaseGenerationContext
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator


class BaseContextBuilder(ABC):
    """Builds a flattened Jinja2 context from a normalized ModuleConfig."""

    def __init__(
        self,
        module_config: BaseModuleConfig,
        api_parser: ApiSpecParser,
        collector: ValidationErrorCollector,
    ):
        """
        Initializes the builder.

        Args:
            module_config (ModuleConfig): The validated configuration for one module.
            api_parser (dict): The OpenAPI specification parser, needed for resolving refs.
            collector: The validation error collector instance.
        """
        self.module_config = module_config
        self.api_parser = api_parser
        self.collector = collector
        # Create an instance of the ReturnBlockGenerator.
        # It needs the full API spec to be able to resolve $ref pointers
        # that may appear in the response schemas.
        self.return_generator = ReturnBlockGenerator(api_parser.api_spec)

    @abstractmethod
    def build(
        self, collection_namespace: str, collection_name: str
    ) -> BaseGenerationContext:
        """
        Main entry point to build the full, flattened context for a single module.
        It orchestrates the creation of all necessary data for the template.
        """
        ...

    def _build_documentation_data(
        self,
        module_name: str,
        parameters: AnsibleModuleParams,
        collection_namespace: str,
        collection_name: str,
    ) -> dict[str, Any]:
        """Builds the DOCUMENTATION block as a Python dictionary."""
        fqcn = f"{collection_namespace}.{collection_name}.{module_name}"
        doc = {
            "module": fqcn,
            "short_description": self.module_config.description,
            "version_added": "0.1",
            "description": [self.module_config.description],
            "requirements": ["python = 3.11", "waldur-api-client"],
            "options": {},
        }
        doc["options"].update({**AUTH_OPTIONS})
        for name, opts in parameters.items():
            doc_data = {
                k: v
                for k, v in opts.items()
                if k in ["description", "required", "type", "choices"] and v is not None
            }
            if "required" not in doc_data:
                doc_data["required"] = False
            doc["options"][name] = doc_data
        return doc
