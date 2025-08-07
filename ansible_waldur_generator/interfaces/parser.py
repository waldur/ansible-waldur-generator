from abc import ABC, abstractmethod
from typing import Any

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.helpers import ValidationErrorCollector
from ansible_waldur_generator.interfaces.config import BaseModuleConfig


class BaseConfigParser(ABC):
    """Abstract base class for all module config parsers."""

    def __init__(
        self,
        module_key: str,
        raw_config: dict[str, Any],
        api_parser: ApiSpecParser,
        collector: ValidationErrorCollector,
    ):
        self.module_key = module_key
        self.raw_config = raw_config
        self.api_parser = api_parser
        self.collector = collector
        self.context_str = f"Module '{module_key}'"

    @abstractmethod
    def parse(self) -> BaseModuleConfig:
        """
        Main entry point for a specific parser. Each subclass must implement this.
        It should normalize, build, and validate the config object.
        """
        ...
