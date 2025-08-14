from abc import ABC, abstractmethod
from typing import Any

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.helpers import ValidationErrorCollector
from ansible_waldur_generator.interfaces.config import BaseModuleConfig
from ansible_waldur_generator.models import AnsibleModuleParams
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator


class BaseContextBuilder(ABC):
    """Builds a template context from a normalized ModuleConfig."""

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
    def _build_examples(
        self,
        module_name: str,
        parameters: AnsibleModuleParams,
        collection_namespace: str,
        collection_name: str,
    ) -> list[dict]: ...

    @abstractmethod
    def _build_return_block(self) -> dict: ...

    @abstractmethod
    def _build_runner_context(self) -> Any: ...

    @abstractmethod
    def _build_parameters(self) -> AnsibleModuleParams: ...
