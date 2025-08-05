from abc import ABC, abstractmethod

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
        self, module_key: str, raw_config, op_map, collector: ValidationErrorCollector
    ) -> BaseConfigParser: ...

    @abstractmethod
    def get_builder(
        self,
        module_config: BaseModuleConfig,
        api_spec_data,
        collector: ValidationErrorCollector,
    ) -> BaseContextBuilder: ...

    @abstractmethod
    def get_template_name(self) -> str: ...
