from pydantic import BaseModel, Field, field_validator

from ansible_waldur_generator.models import ApiOperation, PluginModuleResolver


class FactsModuleConfig(BaseModel):
    """Configuration for 'facts' type modules."""

    description: str | None = None
    resource_type: str
    list_operation: ApiOperation | None = None
    retrieve_operation: ApiOperation | None = None
    many: bool = False
    identifier_param: str = "name"
    resolvers: dict[str, PluginModuleResolver] = Field(default_factory=dict)

    @field_validator("description", mode="before")
    def set_description(cls, v, values):
        if v is None:
            resource_type = values.data.get("resource_type", "").replace("_", " ")
            return f"Get an existing {resource_type}."
        return v
