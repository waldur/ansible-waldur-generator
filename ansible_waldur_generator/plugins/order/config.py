from pydantic import BaseModel, Field
from typing import Dict, List

from ansible_waldur_generator.models import ApiOperation
from ansible_waldur_generator.plugins.crud.config import ModuleResolver


class AttributeParam(BaseModel):
    name: str
    type: str = "string"
    required: bool = False
    description: str | None = None
    is_resolved: bool = False
    choices: List[str] = Field(default_factory=list)


class OrderModuleConfig(BaseModel):
    resource_type: str
    description: str = ""
    existence_check_op: ApiOperation
    update_op: ApiOperation | None = None
    update_check_fields: List[str] = Field(default_factory=list)
    attribute_params: List[AttributeParam] = Field(default_factory=list)
    resolvers: Dict[str, ModuleResolver] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True
