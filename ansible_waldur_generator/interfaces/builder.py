from abc import ABC, abstractmethod
from typing import Any

from ansible_waldur_generator.helpers import ValidationErrorCollector
from ansible_waldur_generator.interfaces.config import BaseModuleConfig
from ansible_waldur_generator.models import BaseGenerationContext


class BaseContextBuilder(ABC):
    """Builds a flattened Jinja2 context from a normalized ModuleConfig."""

    def __init__(
        self,
        module_config: BaseModuleConfig,
        api_spec_data: dict[str, Any],
        collector: ValidationErrorCollector,
    ):
        """
        Initializes the builder.

        Args:
            module_config (ModuleConfig): The validated configuration for one module.
            api_spec_data (dict): The full OpenAPI specification data, needed for resolving refs.
            collector: The validation error collector instance.
        """
        self.module_config = module_config
        self.api_spec = api_spec_data
        self.collector = collector

    @abstractmethod
    def build(self) -> BaseGenerationContext:
        """
        Main entry point to build the full, flattened context for a single module.
        It orchestrates the creation of all necessary data for the template.
        """
        ...
