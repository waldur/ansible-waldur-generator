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
            data = values.data
            resource_type = data.get("resource_type", "").replace("_", " ")
            # Check the 'many' flag to generate a more accurate description.
            if data.get("many", False):
                return f"Get a list of {resource_type}s."
            else:
                return f"Get facts about a single {resource_type}."
        return v
