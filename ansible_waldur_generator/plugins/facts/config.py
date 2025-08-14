from typing import List, Dict
from pydantic import BaseModel, Field, field_validator

from ansible_waldur_generator.models import ApiOperation


class ContextParam(BaseModel):
    name: str
    type: str = "str"
    required: bool = False
    description: str | None = None
    resolver: Dict[str, str]

    @field_validator("resolver")
    def resolver_must_contain_required_keys(cls, v):
        required_keys = {"list", "retrieve", "filter_key"}
        if not required_keys.issubset(v):
            raise ValueError(f"Resolver must contain {required_keys}")
        return v


class FactsModuleConfig(BaseModel):
    """Configuration for 'facts' type modules."""

    description: str | None = None
    resource_type: str
    list_operation: ApiOperation
    retrieve_operation: ApiOperation
    context_params: List[ContextParam] = Field(default_factory=list)
    many: bool = False
    identifier_param: str = "name"

    @field_validator("description", mode="before")
    def set_description(cls, v, values):
        if v is None:
            resource_type = values.data.get("resource_type", "").replace("_", " ")
            return f"Get an existing {resource_type}."
        return v

    class Config:
        arbitrary_types_allowed = True
