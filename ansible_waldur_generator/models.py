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
