"""
This module defines the core data structures used throughout the Ansible module generator.
Using dataclasses provides type hinting, immutability (where desired), and a clear
structure for the data passed between the parser, builder, and generator components.

It uses a class hierarchy for GenerationContext to provide strong typing for
different module types.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

# A type alias for clarity, representing a dictionary of Ansible parameter options.
AnsibleModuleParams = Dict[str, Dict[str, Any]]


"""
Example SdkOperation for reference:

projects_create_op = SdkOperation(
    sdk_module='waldur_api_client.api.projects',
    sdk_function='projects_create',
    
    model_class='ProjectRequest',
    model_module='waldur_api_client.models.project_request',
    model_schema={
        'type': 'object',
        'properties': {
            'uuid': {
                'type': 'string', 
                'format': 'uuid', 
                'readOnly': True, 
                'description': 'The UUID of the project, assigned by the server.'
            },
            'name': {
                'type': 'string', 
                'description': 'The name of the new project.'
            },
            'customer': {
                'type': 'string', 
                'format': 'uri', 
                'description': 'URL of the customer organization.'
            },
        },
        'required': ['name', 'customer']
    },
    
    raw_spec={
        'summary': 'Create a new project',
        'operationId': 'projects_create',
        'tags': ['projects'],
        'requestBody': {
            'content': {
                'application/json': {
                    'schema': {
                        '$ref': '#/components/schemas/ProjectRequest'
                    }
                }
            }
        }
    }
)
"""


@dataclass(frozen=True)
class SdkOperation:
    """
    Represents all the necessary information about a single SDK operation,
    parsed from the OpenAPI specification. 'frozen=True' makes instances immutable.
    """

    sdk_module: str
    sdk_function: str
    model_class: Optional[str] = None
    model_module: Optional[str] = None
    model_schema: Optional[Dict[str, Any]] = None
    raw_spec: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModuleIdempotencySection:
    """
    Represents a configuration section for an idempotency action, like
    'existence_check', 'create', or 'absent'.
    """

    operationId: str

    # This field will be populated by the parser with the full SdkOperation object.
    sdk_op: Optional[SdkOperation] = None

    # Additional configuration specific to the section.
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModuleResolver:
    """
    Represents the configuration for a single parameter resolver.
    """

    list_op_id: str
    retrieve_op_id: str
    error_message: str

    # These fields will be populated by the parser.
    list_op: Optional[SdkOperation] = None
    retrieve_op: Optional[SdkOperation] = None


@dataclass
class ModuleConfig:
    """
    Represents the complete, normalized configuration for a single Ansible module
    to be generated.
    """

    module_key: str  # The key from the generator_config.yaml (e.g., 'project')
    resource_type: str
    description: str

    # Sections defining the module's logic.
    existence_check: ModuleIdempotencySection
    present_create: ModuleIdempotencySection
    absent_destroy: ModuleIdempotencySection

    # Optional sections.
    resolvers: Dict[str, ModuleResolver] = field(default_factory=dict)
    skip_resolver_check: List[str] = field(default_factory=list)


@dataclass
class BaseGenerationContext:
    """
    Data object passed from the ContextBuilder to the Jinja2 template.
    It contains simple, direct keys for the template to consume, minimizing logic in the template itself.

    Base class for all generation contexts contains fields that are
    common to every type of generated module, such as documentation and imports.
    """

    # The final name of the module file, e.g., 'waldur_project'.
    module_name: str

    # The short description for the module's documentation header.
    description: str

    # The complete, generated dictionary of parameters for Ansible's `argument_spec`.
    parameters: AnsibleModuleParams

    # A list of unique SDK imports required by the module's logic.
    # Example: [{'module': 'waldur_api_client.api.projects', 'function': 'projects_create'}]
    sdk_imports: List[Dict[str, str]]

    # The full `DOCUMENTATION` block, pre-rendered as a single, valid YAML string.
    documentation_yaml: str

    # The full `EXAMPLES` block, pre-rendered as a single, valid YAML string.
    examples_yaml: str

    def to_dict(self) -> Dict[str, Any]:
        """Converts the dataclass instance to a dictionary for Jinja2."""
        return asdict(self)


@dataclass
class ResourceGenerationContext(BaseGenerationContext):
    # The user-friendly name of the resource, e.g., 'project'. Used in messages and docs.
    resource_type: str

    # The name of the SDK function for the existence check (e.g., 'projects_list').
    existence_check_func: str

    # The name of the SDK function for creating the resource (e.g., 'projects_create').
    present_create_func: str

    # The name of the Python model class for the creation request body (e.g., 'ProjectRequest').
    present_create_model_class: Optional[str]

    # The raw OpenAPI schema for the creation request model.
    present_create_model_schema: Dict[str, Any]

    # The name of the SDK function for deleting the resource (e.g., 'projects_destroy').
    absent_destroy_func: str

    # The name of the field on the resource object to use as the path parameter for deletion (e.g., 'uuid').
    absent_destroy_path_param: str

    # A simplified dictionary of resolvers for the template to iterate over.
    # Example: {'customer': {'list_func': 'customers_list', 'retrieve_func': 'customers_retrieve', ...}}
    resolvers: Dict[str, Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        """
        Converts the dataclass instance to a dictionary. This is the required
        format for the Jinja2 `render` method.
        """
        # asdict from the dataclasses module recursively converts the object to a dict.
        return asdict(self)
