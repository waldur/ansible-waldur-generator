from dataclasses import dataclass


@dataclass
class BaseModuleConfig:
    """Base class for all module configurations. Contains common fields."""

    module_key: str
    description: str
