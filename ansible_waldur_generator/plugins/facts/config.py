from pydantic import BaseModel, Field, field_validator

from ansible_waldur_generator.models import ApiOperation, ContextParam


class FactsModuleConfig(BaseModel):
    """Configuration for 'facts' type modules."""

    description: str | None = None
    resource_type: str
    list_operation: ApiOperation | None = None
    retrieve_operation: ApiOperation | None = None
    context_params: list[ContextParam] = Field(default_factory=list)
    many: bool = False
    identifier_param: str = "name"

    @field_validator("description", mode="before")
    def set_description(cls, v, values):
        if v is None:
            resource_type = values.data.get("resource_type", "").replace("_", " ")
            return f"Get an existing {resource_type}."
        return v
