from pydantic import BaseModel, Field, field_validator

from ansible_waldur_generator.models import ApiOperation, PluginModuleResolver


class ActionsModuleConfig(BaseModel):
    """Configuration for 'actions' type modules."""

    description: str | None = None
    resource_type: str
    check_operation: ApiOperation
    retrieve_operation: ApiOperation
    actions: dict[str, ApiOperation] = Field(default_factory=dict)
    resolvers: dict[str, PluginModuleResolver] = Field(default_factory=dict)
    identifier_param: str = "name"

    @field_validator("description", mode="before")
    def set_description(cls, v, values):
        if v is None:
            resource_type = values.data.get("resource_type", "").replace("_", " ")
            return f"Perform actions on an existing {resource_type}."
        return v
