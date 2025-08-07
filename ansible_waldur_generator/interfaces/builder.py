from abc import ABC, abstractmethod

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.helpers import ValidationErrorCollector
from ansible_waldur_generator.interfaces.config import BaseModuleConfig
from ansible_waldur_generator.models import BaseGenerationContext


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

    @abstractmethod
    def build(self) -> BaseGenerationContext:
        """
        Main entry point to build the full, flattened context for a single module.
        It orchestrates the creation of all necessary data for the template.
        """
        ...
