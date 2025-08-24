from pydantic import BaseModel, Field
from typing import Dict, List

from ansible_waldur_generator.models import ApiOperation


class UpdateActionConfig(BaseModel):
    """Configuration for a complex, idempotent update action."""

    operation: ApiOperation
    param: str  # The Ansible parameter providing the data.
    compare_key: (
        str  # The key on the existing resource to compare against for idempotency.
    )


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

    # Optional mapping to a different attribute name in the API payload.
    maps_to: str | None = None


class WaitConfig(BaseModel):
    """Configuration for polling an asynchronous task."""

    ok_states: List[str] = Field(default_factory=lambda: ["OK"])
    erred_states: List[str] = Field(default_factory=lambda: ["Erred"])
    state_field: str = "state"


class OrderModuleConfig(BaseModel):
    offering_type: str | None = None
    resource_type: str
    description: str = ""
    existence_check_op: ApiOperation
    update_op: ApiOperation | None = None
    update_check_fields: List[str] = Field(default_factory=list)
    update_actions: Dict[str, UpdateActionConfig] = Field(default_factory=dict)
    attribute_params: List[ParameterConfig] = Field(default_factory=list)
    termination_attributes: List[ParameterConfig] = Field(default_factory=list)
    resolvers: Dict[str, OrderModuleResolver] = Field(default_factory=dict)
    has_limits: bool = False
    wait_config: WaitConfig | None = None
    transformations: Dict[str, str] = Field(default_factory=dict)
