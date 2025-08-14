from dataclasses import dataclass, field
from typing import Any

from ansible_waldur_generator.interfaces.config import BaseModuleConfig
from ansible_waldur_generator.models import ApiOperation


@dataclass
class ModuleResolver:
    """
    Represents the configuration for a single parameter resolver.
    """

    list_op_id: str
    retrieve_op_id: str
    error_message: str

    # These fields will be populated by the parser.
    list_op: ApiOperation | None = None
    retrieve_op: ApiOperation | None = None


@dataclass
class CrudModuleConfig(BaseModuleConfig):
    """
    Represents the complete, normalized configuration for a single Ansible module
    to be generated.
    """

    resource_type: str

    check_section: ApiOperation
    create_section: ApiOperation
    destroy_section: ApiOperation

    # Additional configuration for the check section (existence check)
    # This replaces the 'config' field that was previously used
    check_section_config: dict[str, Any] = field(default_factory=dict)

    resolvers: dict[str, ModuleResolver] = field(default_factory=dict)
    skip_resolver_check: list[str] = field(default_factory=list)
