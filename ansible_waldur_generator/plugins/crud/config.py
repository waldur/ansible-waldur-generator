from dataclasses import dataclass, field
from typing import Any

from ansible_waldur_generator.interfaces.config import BaseModuleConfig
from ansible_waldur_generator.models import SdkOperation


@dataclass
class ModuleIdempotencySection:
    """
    Represents a configuration section for an idempotency action, like
    'existence_check', 'create', or 'absent'.
    """

    operationId: str

    # This field will be populated by the parser with the full SdkOperation object.
    sdk_op: SdkOperation | None = None

    # Additional configuration specific to the section.
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModuleResolver:
    """
    Represents the configuration for a single parameter resolver.
    """

    list_op_id: str
    retrieve_op_id: str
    error_message: str

    # These fields will be populated by the parser.
    list_op: SdkOperation | None = None
    retrieve_op: SdkOperation | None = None


@dataclass
class CrudModuleConfig(BaseModuleConfig):
    """
    Represents the complete, normalized configuration for a single Ansible module
    to be generated.
    """

    resource_type: str

    existence_check: ModuleIdempotencySection
    present_create: ModuleIdempotencySection
    absent_destroy: ModuleIdempotencySection

    resolvers: dict[str, ModuleResolver] = field(default_factory=dict)
    skip_resolver_check: list[str] = field(default_factory=list)
