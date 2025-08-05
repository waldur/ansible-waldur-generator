from abc import ABC, abstractmethod

from ansible_waldur_generator.interfaces.builder import BaseContextBuilder
from ansible_waldur_generator.interfaces.parser import BaseConfigParser


class BasePlugin(ABC):
    """
    The interface that all generator plugins must implement.
    """

    @abstractmethod
    def get_type_name(self) -> str: ...

    @abstractmethod
    def get_parser(
        self, module_key, raw_config, op_map, collector
    ) -> BaseConfigParser: ...

    @abstractmethod
    def get_builder(
        self, module_config, api_spec_data, collector
    ) -> BaseContextBuilder: ...

    @abstractmethod
    def get_template_name(self) -> str: ...
