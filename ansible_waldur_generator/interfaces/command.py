from typing import Any, Dict


class Command:
    """
    A self-contained object representing a single, atomic change to the system.

    This class encapsulates all information needed to perform an API request and
    to represent the change in a user-friendly diff format. It is the core of
    the "plan-and-execute" workflow.
    """

    def __init__(
        self,
        runner,
        method: str,
        path: str,
        command_type: str,
        description: str,
        data: Dict[str, Any] | None = None,
        path_params: Dict[str, Any] | None = None,
        wait_config: Dict[str, Any] | None = None,
    ):
        """
        Initializes the command.

        Args:
            runner: The runner instance that will execute this command.
            method (str): The HTTP method (e.g., 'POST', 'PATCH', 'DELETE').
            path (str): The API endpoint path.
            command_type (str): The logical type of command ('create', 'update',
                                'delete', 'action', 'order'). This helps the runner
                                correctly update its state after execution.
            description (str): A human-readable summary of the command's purpose.
            data (dict, optional): The request body payload.
            path_params (dict, optional): Parameters to format into the path.
            wait_config (dict, optional): Configuration for the generic waiter if this
                                          command triggers an async task.
        """
        self.runner = runner
        self.method = method
        self.path = path
        self.command_type = command_type
        self.description = description
        self.data = data
        self.path_params = path_params
        self.wait_config = wait_config
        self.response = None
        self.status_code = 0

    def execute(self) -> Any:
        """
        Executes the command by sending the configured HTTP request.
        Stores the response and status code on the instance for later inspection.

        Returns:
            The parsed JSON response from the API.
        """
        self.response, self.status_code = self.runner.send_request(
            self.method, self.path, data=self.data, path_params=self.path_params
        )
        return self.response

    def serialize_request(self) -> dict:
        """
        Generates a serializable dictionary representing the HTTP request this
        command will make. This is used for Ansible's command output.
        """
        # Format path with path_params if they exist.
        final_path = self.path
        if self.path_params:
            final_path = self.path.format(**self.path_params)

        # Build the full URL.
        api_url = self.runner.module.params["api_url"].rstrip("/")
        full_url = f"{api_url}/{final_path.lstrip('/')}"

        # Assemble the final dictionary.
        serialized: dict[str, str | dict] = {
            "method": self.method,
            "url": full_url,
            "description": self.description,
        }
        if self.data:
            serialized["body"] = self.data

        return serialized
