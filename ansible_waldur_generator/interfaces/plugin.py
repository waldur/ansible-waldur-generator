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

    def get_runner_path(self) -> str | None:
        module = sys.modules[self.__class__.__module__]
        if not module.__file__:
            return None
        plugin_dir = os.path.dirname(module.__file__)
        runner_path = os.path.join(plugin_dir, "runner.py")
        return runner_path if os.path.exists(runner_path) else None
