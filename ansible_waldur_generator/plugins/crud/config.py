from pydantic import BaseModel, Field
from typing import Dict, List, Any

from ansible_waldur_generator.models import ApiOperation


class ModuleResolver(BaseModel):
    """
    Defines how to resolve a user-friendly name or UUID into a full API URL.
    This is essential for parameters that represent foreign keys, like linking a
    project to a customer.
    """

    # The API operation used to find a resource by its name (a list operation with filtering).
    list_operation: ApiOperation

    # The API operation used to find a resource directly by its UUID (a retrieve operation).
    retrieve_operation: ApiOperation

    # A user-friendly error message to display if the resource cannot be found.
    error_message: str | None = None

    class Config:
        # Pydantic configuration to allow non-standard types like ApiOperation.
        arbitrary_types_allowed = True


class UpdateAction(BaseModel):
    """
    Represents a special, non-standard update action that is triggered by a
    specific Ansible parameter. This is used for operations like setting security
    group rules, which involve a dedicated POST request rather than a simple PATCH.
    """

    # The API operation to be called for this action (e.g., 'openstack_security_groups_set_rules').
    operation: ApiOperation

    # The name of the Ansible parameter that triggers this action and provides its data (e.g., 'rules').
    param: str

    class Config:
        arbitrary_types_allowed = True


class UpdateConfig(BaseModel):
    """
    Groups all configurations related to updating an existing resource.
    This allows the module to handle both simple field updates and complex,
    action-based updates within the same `state: present` logic.
    """

    # A list of Ansible parameter names that correspond to simple, mutable fields
    # on the resource. If any of these parameters have changed, a PATCH request
    # will be sent to the `update_operation` endpoint.
    # Example: ["name", "description"]
    fields: List[str] | None = None

    # A dictionary mapping a logical action name to its configuration. This is for
    # more complex updates that require calling a special action endpoint.
    # The key is a descriptive name (e.g., "set_rules"), and the value is an UpdateAction object.
    actions: Dict[str, UpdateAction] = Field(default_factory=dict)


class CrudModuleConfig(BaseModel):
    """
    The main configuration model for a 'crud' type Ansible module.
    It defines all the necessary API operations and mappings to manage the
    full lifecycle (Create, Read, Update, Delete) of a resource.
    """

    # A user-friendly, singular name for the resource being managed (e.g., "project").
    resource_type: str

    # A short description for the generated Ansible module. If omitted, one is auto-generated.
    description: str | None = None

    # --- Core Lifecycle Operations ---

    # The base part of the OpenAPI operationId, used to infer full operation IDs.
    # Example: 'projects' becomes 'projects_list', 'projects_create', etc.
    base_operation_id: str | None = None

    # The API operation for checking if a resource exists (typically a 'list' endpoint).
    check_operation: ApiOperation | None = None

    # The API operation for creating a new resource when `state: present`.
    # This can be a nested endpoint (e.g., under a parent resource).
    create_operation: ApiOperation | None = None

    # The API operation for deleting a resource when `state: absent`.
    destroy_operation: ApiOperation | None = None

    # The API operation for updating a resource with simple field changes (e.g., PATCH).
    # This is optional; if omitted, only action-based updates will be possible.
    update_operation: ApiOperation | None = None

    # --- Advanced Configuration ---

    # Detailed configuration for how to handle updates for an existing resource.
    # If this is not defined, the module will be idempotent on creation but will not
    # perform any updates on existing resources.
    update_config: UpdateConfig | None = None

    # A mapping of operation types to their path parameter configurations.
    # This is critical for nested endpoints, especially for 'create'. It maps the
    # placeholder in the URL path (e.g., {uuid}) to the name of an Ansible parameter
    # (e.g., 'tenant').
    # Example: path_param_maps: { create: { uuid: "tenant" } }
    path_param_maps: Dict[str, Dict[str, str]] = Field(default_factory=dict)

    # Defines the parameters used by the `check_operation` to find a resource.
    # By default, this is configured to search by `name`.
    check_operation_config: Dict[str, Any] = Field(default_factory=dict)

    # A dictionary of resolvers for any parameters that need to be converted
    # from names/UUIDs to full API URLs. The key is the parameter name.
    resolvers: Dict[str, ModuleResolver] = Field(default_factory=dict)

    # A list of parameter names that have 'format: uri' but should NOT be treated
    # as needing a resolver. This is an escape hatch for special cases.
    skip_resolver_check: List[str] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True
