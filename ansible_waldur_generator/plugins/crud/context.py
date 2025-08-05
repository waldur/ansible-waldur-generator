from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class CrudRunnerContext:
    # The user-friendly name of the resource, e.g., 'project'. Used in messages and docs.
    resource_type: str

    # The name of the SDK function for the existence check (e.g., 'projects_list').
    existence_check_func: str

    # The name of the SDK function for creating the resource (e.g., 'projects_create').
    present_create_func: str

    # The name of the Python model class for the creation request body (e.g., 'ProjectRequest').
    present_create_model_class: str | None

    model_param_names: list[str]

    # The name of the SDK function for deleting the resource (e.g., 'projects_destroy').
    absent_destroy_func: str

    # The name of the field on the resource object to use as the path parameter for deletion (e.g., 'uuid').
    absent_destroy_path_param: str

    # A simplified dictionary of resolvers for the template to iterate over.
    # Example: {'customer': {'list_func': 'customers_list', 'retrieve_func': 'customers_retrieve', ...}}
    resolvers: Dict[str, Dict[str, Any]]
