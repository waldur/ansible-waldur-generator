from dataclasses import dataclass, field

from ansible_waldur_generator.interfaces.config import BaseModuleConfig
from ansible_waldur_generator.models import ApiOperation


@dataclass
class FactsModuleConfig(BaseModuleConfig):
    """Configuration for 'facts' type modules."""

    resource_type: str
    list_op: ApiOperation
    retrieve_op: ApiOperation
    many: bool
    identifier_param: str = "name"
    context_params: list[dict] = field(default_factory=list)
