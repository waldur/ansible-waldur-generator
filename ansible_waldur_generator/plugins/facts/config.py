from dataclasses import dataclass, field

from ansible_waldur_generator.interfaces.config import BaseModuleConfig
from ansible_waldur_generator.plugins.crud.config import ModuleIdempotencySection


@dataclass
class FactsModuleConfig(BaseModuleConfig):
    """Configuration for 'facts' type modules."""

    resource_type: str
    list_op: ModuleIdempotencySection
    retrieve_op: ModuleIdempotencySection
    identifier_param: str = "name"
    context_params: list[dict] = field(default_factory=list)
