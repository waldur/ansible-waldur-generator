from typing import List
from pydantic import BaseModel, Field, field_validator

from ansible_waldur_generator.models import ApiOperation


class ContextParam(BaseModel):
    name: str
    type: str = "str"
    required: bool = False
    description: str | None = None
    resolver: str
    # `resolver` is just a string, representing the base_operation_id
    # of the parent resource (e.g., "openstack_tenants")
    filter_key: str


class FactsModuleConfig(BaseModel):
    """Configuration for 'facts' type modules."""

    description: str | None = None
    resource_type: str
    list_operation: ApiOperation | None = None
    retrieve_operation: ApiOperation | None = None
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
