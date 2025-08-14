from pydantic import BaseModel, Field
from typing import Dict, List, Any

from ansible_waldur_generator.models import ApiOperation


class ModuleResolver(BaseModel):
    list_operation: ApiOperation
    retrieve_operation: ApiOperation
    error_message: str | None = None

    class Config:
        arbitrary_types_allowed = True


class CrudModuleConfig(BaseModel):
    resource_type: str
    description: str | None = None
    check_section: ApiOperation
    create_section: ApiOperation
    destroy_section: ApiOperation
    check_section_config: Dict[str, Any] = Field(default_factory=dict)
    resolvers: Dict[str, ModuleResolver] = Field(default_factory=dict)
    skip_resolver_check: List[str] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True
