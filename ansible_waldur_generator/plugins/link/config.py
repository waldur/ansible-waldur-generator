from pydantic import BaseModel, Field
from typing import List

from ansible_waldur_generator.models import ApiOperation, PluginModuleResolver
from ansible_waldur_generator.plugins.order.config import ParameterConfig


class LinkResourceConfig(BaseModel):
    """Configuration for one side of the link (source or target)."""

    param: str
    resource_type: str
    retrieve_op: ApiOperation | None = None


class LinkModuleConfig(BaseModel):
    """Configuration for a 'link' type module."""

    description: str
    resource_type: str
    source: LinkResourceConfig
    target: LinkResourceConfig
    link_op: ApiOperation
    unlink_op: ApiOperation
    link_check_key: str
    link_params: List[ParameterConfig] = Field(default_factory=list)
    resolvers: dict[str, PluginModuleResolver] = Field(default_factory=dict)
