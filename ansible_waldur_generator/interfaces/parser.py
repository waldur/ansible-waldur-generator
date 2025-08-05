from abc import ABC, abstractmethod
from typing import Any

from ansible_waldur_generator.helpers import ValidationErrorCollector
from ansible_waldur_generator.interfaces.config import BaseModuleConfig
from ansible_waldur_generator.models import SdkOperation


class BaseConfigParser(ABC):
    """Abstract base class for all module config parsers."""

    def __init__(
        self,
        module_key: str,
        raw_config: dict[str, Any],
        op_map: dict[str, SdkOperation],
        collector: ValidationErrorCollector,
    ):
        self.module_key = module_key
        self.raw_config = raw_config
        self.op_map = op_map
        self.collector = collector
        self.context_str = f"Module '{module_key}'"

    @abstractmethod
    def parse(self) -> BaseModuleConfig:
        """
        Main entry point for a specific parser. Each subclass must implement this.
        It should normalize, build, and validate the config object.
        """
        ...
