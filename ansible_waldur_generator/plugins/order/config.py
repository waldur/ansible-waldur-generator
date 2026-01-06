from pydantic import BaseModel, Field
from typing import Dict, List, Any

from ansible_waldur_generator.models import ApiOperation, PluginModuleResolver


class UpdateActionConfig(BaseModel):
    """Configuration for a complex, idempotent update action."""

    operation: ApiOperation
    param: str  # The Ansible parameter providing the data.
    compare_key: (
        str  # The key on the existing resource to compare against for idempotency.
    )
    maps_to: str | None = None


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
    retrieve_op: ApiOperation | None = None
    update_op: ApiOperation | None = None
    update_fields: List[str] = Field(default_factory=list)
    update_actions: Dict[str, UpdateActionConfig] = Field(default_factory=dict)
    attribute_params: List[ParameterConfig] = Field(default_factory=list)
    termination_attributes: List[ParameterConfig] = Field(default_factory=list)
    resolvers: Dict[str, PluginModuleResolver] = Field(default_factory=dict)
    has_limits: bool = False
    wait_config: WaitConfig | None = None
    transformations: Dict[str, str] = Field(default_factory=dict)

    # The query parameter name to use for name-based lookups in check_existence.
    # Defaults to "name_exact". Some API endpoints use different parameter names.
    name_query_param: str = "name_exact"

    # List of paths to external YAML files containing extra examples OR inline dictionaries/lists
    extra_examples: List[Any] = Field(default_factory=list)
