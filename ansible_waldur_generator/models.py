"""
This module defines the core data structures used throughout the Ansible module generator.
Using dataclasses provides type hinting, immutability (where desired), and a clear
structure for the data passed between the parser, builder, and generator components.

It uses a class hierarchy for GenerationContext to provide strong typing for
different module types.
"""

from dataclasses import dataclass, field, asdict
from types import ModuleType
from typing import Optional, List, Dict, Any

# A type alias for clarity, representing a dictionary of Ansible parameter options.
AnsibleModuleParams = Dict[str, Dict[str, Any]]


@dataclass(frozen=True)
class SdkOperation:
    """
    Represents all the necessary information about a single SDK operation,
    parsed from the OpenAPI specification. 'frozen=True' makes instances immutable.
    """

    sdk_module_name: str  # e.g., 'waldur_api_client.api.projects'
    sdk_function_name: str  # e.g., 'projects_create'
    sdk_function: ModuleType  # The actual imported function object/module

    model_class_name: Optional[str] = None  # e.g., 'ProjectRequest'
    model_module_name: Optional[str] = (
        None  # e.g., 'waldur_api_client.models.project_request'
    )
    model_class: Optional[type] = None  # The actual imported class object

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

    runner_class_name: str
    runner_import_path: str
    runner_context_string: Any

    def to_dict(self) -> Dict[str, Any]:
        """Converts the dataclass instance to a dictionary for Jinja2."""
        return asdict(self)
