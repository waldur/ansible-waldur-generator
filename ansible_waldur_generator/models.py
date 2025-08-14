"""
This module defines the core data structures used throughout the Ansible module generator.
Using dataclasses provides type hinting, immutability (where desired), and a clear
structure for the data passed between the parser, builder, and generator components.

It uses a class hierarchy for GenerationContext to provide strong typing for
different module types.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any

# A type alias for clarity, representing a dictionary of Ansible parameter options.
AnsibleModuleParams = Dict[str, Dict[str, Any]]


@dataclass(frozen=True)
class ApiOperation:
    """
    Represents all the necessary information about a single API operation,
    parsed from the OpenAPI specification.
    """

    path: str  # The API path, e.g., /api/projects/
    method: str  # The HTTP method, e.g., GET, POST
    operation_id: str  # The OpenAPI operationId
    model_schema: Optional[Dict[str, Any]] = (
        None  # The JSON schema for the request body
    )
    raw_spec: Dict[str, Any] = field(
        default_factory=dict
    )  # The raw OpenAPI spec for the operation


@dataclass
class GenerationContext:
    """
    Data object passed from the ContextBuilder to the template.
    It contains simple, direct keys for the template to consume, minimizing logic in the template itself.

    Base class for all generation contexts contains fields that are
    common to every type of generated module, such as documentation and imports.
    """

    argument_spec: dict

    # The full `DOCUMENTATION` block
    documentation: dict

    # The full `EXAMPLES` block
    examples: dict | list[dict]

    # The full `RETURN` block
    return_block: dict

    runner_context: Any
