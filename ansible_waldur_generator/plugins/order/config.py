from pydantic import BaseModel, Field
from typing import Dict, List

from ansible_waldur_generator.models import ApiOperation


class FilterByConfig(BaseModel):
    """
    Defines a dependency for filtering a resolver's list query.
    """

    # The Ansible parameter that provides the filter value (e.g., "offering").
    source_param: str
    # The key to extract from the resolved source_param's response (e.g., "scope_uuid").
    source_key: str
    # The query parameter key for the target API call (e.g., "settings_uuid").
    target_key: str


class OrderModuleResolver(BaseModel):
    """
    Defines how to resolve a parameter, now with support for dependent filtering.
    """

    list_operation: ApiOperation
    retrieve_operation: ApiOperation
    error_message: str | None = None
    # A list of dependencies used to filter the 'list' operation call.
    filter_by: List[FilterByConfig] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True


class ParameterConfig(BaseModel):
    name: str
    type: str = "string"
    format: str | None = None
    required: bool = False
    description: str | None = None
    is_resolved: bool = False
    choices: List[str] = Field(default_factory=list)

    # For type: 'object'
    properties: List["ParameterConfig"] = Field(default_factory=list)

    # For type: 'array'
    items: "ParameterConfig | None" = None

    # For references
    ref: str | None = None


class OrderModuleConfig(BaseModel):
    offering_type: str | None = None
    resource_type: str
    description: str = ""
    existence_check_op: ApiOperation
    update_op: ApiOperation | None = None
    update_check_fields: List[str] = Field(default_factory=list)
    attribute_params: List[ParameterConfig] = Field(default_factory=list)
    resolvers: Dict[str, OrderModuleResolver] = Field(default_factory=dict)
    has_limits: bool = False

    class Config:
        arbitrary_types_allowed = True
