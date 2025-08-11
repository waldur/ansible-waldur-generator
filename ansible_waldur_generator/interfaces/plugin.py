from abc import ABC, abstractmethod
import os
import sys

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.helpers import ValidationErrorCollector
from ansible_waldur_generator.interfaces.builder import BaseContextBuilder
from ansible_waldur_generator.interfaces.config import BaseModuleConfig
from ansible_waldur_generator.interfaces.parser import BaseConfigParser


class BasePlugin(ABC):
    """
    The interface that all generator plugins must implement.
    """

    @abstractmethod
    def get_type_name(self) -> str: ...

    @abstractmethod
    def get_parser(
        self,
        module_key: str,
        raw_config,
        api_parser: ApiSpecParser,
        collector: ValidationErrorCollector,
    ) -> BaseConfigParser: ...

    @abstractmethod
    def get_builder(
        self,
        module_config: BaseModuleConfig,
        api_parser: ApiSpecParser,
        collector: ValidationErrorCollector,
    ) -> BaseContextBuilder: ...

    def get_runner_path(self) -> str | None:
        plugin_dir = os.path.dirname(sys.modules[self.__class__.__module__].__file__)
        runner_path = os.path.join(plugin_dir, "runner.py")
        return runner_path if os.path.exists(runner_path) else None
