from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class CrudRunnerContext:
    # The user-friendly name of the resource, e.g., 'project'. Used in messages and docs.
    resource_type: str

    model_param_names: list[str]

    # A simplified dictionary of resolvers for the template to iterate over.
    # Example: {'customer': {'list_func': 'customers_list', 'retrieve_func': 'customers_retrieve', ...}}
    resolvers: Dict[str, Dict[str, Any]]
