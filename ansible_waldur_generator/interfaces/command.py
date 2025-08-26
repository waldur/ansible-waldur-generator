from abc import ABC, abstractmethod
import time
from typing import Any, Dict


class BaseCommand(ABC):
    """
    Abstract base class for a command in the Command pattern.

    Each command is a self-contained object that encapsulates all the information
    needed to perform a single, atomic change to the system. This includes the
    API endpoint, the request payload, and the logic to generate a user-friendly
    diff representation of the change.

    By using commands, we decouple the "planning" phase (deciding what needs to
    change) from the "execution" phase (actually making the API calls).
    """

    def __init__(self, runner, description: str):
        """
        Initializes the command.

        Args:
            runner: The runner instance that will execute this command. This provides
                    access to the `send_request` method and the module context.
            description (str): A human-readable summary of the command's purpose.
        """
        self.runner = runner
        self.description = description

    @abstractmethod
    def execute(self) -> Any:
        """
        Executes the command. This is the only place where a write operation
        (POST, PUT, PATCH, DELETE) should be made to the API.

        Returns:
            The result of the execution, which could be the new state of a resource,
            an HTTP status code, or None.
        """
        pass

    @abstractmethod
    def to_diff(self) -> Dict[str, Any]:
        """
        Generates a dictionary representing the change this command will make.
        This is used to provide a predictive diff for Ansible's check mode and
        to report on the changes that were actually made.

        Returns:
            A dictionary structured for Ansible's diff output.
        """
        pass


class CreateCommand(BaseCommand):
    """A command to create a new resource via a standard POST request."""

    def __init__(
        self,
        runner,
        path: str,
        data: Dict[str, Any],
        path_params: Dict[str, Any] | None = None,
    ):
        """
        Initializes the create command.

        Args:
            runner: The runner instance.
            path (str): The API endpoint for creation (e.g., "/api/projects/").
            data (dict): The fully resolved request body payload.
            path_params (dict, optional): Parameters to format into the path for nested creation.
        """
        super().__init__(runner, f"Create new {runner.context['resource_type']}")
        self.path = path
        self.data = data
        self.path_params = path_params

    def execute(self) -> Any:
        """
        Sends the POST request to the API to create the resource.

        Returns:
            The dictionary representation of the newly created resource.
        """
        resource, _ = self.runner.send_request(
            "POST", self.path, data=self.data, path_params=self.path_params
        )
        return resource

    def to_diff(self) -> Dict[str, Any]:
        """
        Generates a diff showing the attributes of the resource to be created.
        """
        return {"state": "Resource will be created.", "new_attributes": self.data}


class DeleteCommand(BaseCommand):
    """
    A command to delete an existing resource. This can handle both simple DELETE
    requests and more complex POST-based terminations (like in the marketplace).
    """

    def __init__(
        self,
        runner,
        path: str,
        resource_to_delete: Dict[str, Any],
        data: Dict[str, Any] | None = None,
        path_params: Dict[str, Any] | None = None,
        method: str | None = None,
    ):
        """
        Initializes the delete/terminate command.

        Args:
            runner: The runner instance.
            path (str): The API endpoint for deletion (e.g., "/api/projects/{uuid}/").
            resource_to_delete (dict): The current state of the resource for diffing.
            data (dict, optional): A payload for termination actions (e.g., `{'attributes': {'force': True}}`).
            path_params (dict, optional): Parameters to format into the path.
            method (str, optional): The HTTP method to use. If not provided, it defaults
                                    to 'POST' if data is present, otherwise 'DELETE'.
                                    This is crucial for marketplace termination.
        """
        super().__init__(runner, f"Delete {runner.context['resource_type']}")
        self.path = path
        self.resource_to_delete = resource_to_delete
        self.data = data
        self.path_params = path_params
        # Determine the HTTP method based on whether a payload is provided.
        # Simple deletes use DELETE; marketplace terminations use POST.
        self.method = method or ("POST" if self.data else "DELETE")

    def execute(self) -> Any:
        """
        Sends the DELETE or POST request to the API to remove the resource.
        """
        self.runner.send_request(
            self.method, self.path, data=self.data, path_params=self.path_params
        )
        return None  # Deletion returns no resource object.

    def to_diff(self) -> Dict[str, Any]:
        """
        Generates a diff showing the resource that will be deleted.
        """
        diff_obj = {
            "state": "Resource will be deleted.",
            "old_attributes": self.resource_to_delete,
        }
        if self.data:
            diff_obj["termination_options"] = self.data
        return diff_obj


class UpdateCommand(BaseCommand):
    """A command for simple, direct attribute updates via a PATCH request."""

    def __init__(
        self,
        runner,
        path: str,
        changes: list,
        path_params: Dict[str, Any] | None = None,
    ):
        """
        Initializes the update command.

        Args:
            runner: The runner instance.
            path (str): The API endpoint for PATCH updates.
            changes (list): A list of structured change dictionaries, where each is
                            `{'param': str, 'old': any, 'new': any}`.
            path_params (dict, optional): Parameters to format into the path.
        """
        super().__init__(
            runner, f"Update attributes of {runner.context['resource_type']}"
        )
        self.path = path
        self.changes = changes
        self.path_params = path_params

    def execute(self) -> Any:
        """
        Builds a payload from the detected changes and sends the PATCH request.
        """
        # The payload for the API call should only contain the *new* values.
        # The `self.changes` list contains the full old/new context for diffing.
        update_payload = {change["param"]: change["new"] for change in self.changes}
        resource, _ = self.runner.send_request(
            "PATCH", self.path, data=update_payload, path_params=self.path_params
        )
        return resource

    def to_diff(self) -> Dict[str, Any]:
        """
        Generates a diff showing exactly which attributes will be changed.
        """
        return {"updated_attributes": self.changes}


class ActionCommand(BaseCommand):
    """A command for executing complex, idempotent update actions via a POST request."""

    def __init__(
        self,
        runner,
        path: str,
        data: Dict[str, Any],
        param_name: str,
        old_value: Any,
        new_value: Any,
        path_params: Dict[str, Any] | None = None,
    ):
        """
        Initializes the action command.

        Args:
            runner: The runner instance.
            path (str): The specific API endpoint for this action.
            data (dict): The fully resolved payload for the POST request.
            param_name (str): The name of the Ansible parameter that triggered this action.
            old_value (any): The original value of the parameter on the resource (for diff).
            new_value (any): The resolved, desired value for the parameter (for diff).
            path_params (dict, optional): Parameters to format into the path.
        """
        super().__init__(
            runner,
            f"Execute action '{param_name}' on {runner.context['resource_type']}",
        )
        self.path = path
        self.data = data
        self.param_name = param_name
        self.old_value = old_value
        self.new_value = new_value
        self.path_params = path_params
        self.status_code = 0  # Will be populated on execution.

    def execute(self) -> Any:
        """
        Sends the POST request to the action endpoint.

        Returns:
            The HTTP status code of the response, which is crucial for determining
            if the action was synchronous (200) or asynchronous (202).
        """
        _, self.status_code = self.runner.send_request(
            "POST", self.path, data=self.data, path_params=self.path_params
        )
        return self.status_code

    def to_diff(self) -> Dict[str, Any]:
        """
        Generates a diff showing the action to be performed and the change in value.
        """
        return {
            "action": self.param_name,
            "old": self.old_value,
            "new": self.new_value,
        }


class MarketplaceOrderCommand(BaseCommand):
    """
    A specialized command that fully encapsulates the entire marketplace order workflow.

    This command is a self-contained unit of work that handles:
    1. Submitting the initial POST request to create the order.
    2. Polling the order's status until it reaches a terminal state (if `wait` is enabled).
    3. Triggering a final check for the provisioned resource upon completion.
    """

    def __init__(self, runner, order_payload: Dict[str, Any]):
        """
        Initializes the marketplace order command.
        """
        super().__init__(
            runner, f"Create {runner.context['resource_type']} via marketplace order"
        )
        self.order_payload = order_payload
        self.order = None

    def execute(self) -> Any:
        """
        Executes the full order-and-wait workflow.

        Returns:
            The dictionary representation of the final, provisioned resource.
        """
        # --- Step 1: Submit the Order ---
        order, _ = self.runner.send_request(
            "POST", "/api/marketplace-orders/", data=self.order_payload
        )
        self.order = order
        self.runner.order = order

        # --- Step 2: Wait for Completion (if configured) ---
        if self.runner.module.params.get("wait", True) and order:
            # The waiting logic is now encapsulated within the command.
            self._wait_for_order(order["uuid"])

        # --- Step 3: Return the Final Resource ---
        # If waiting was disabled, the resource doesn't exist yet, so we return None.
        # If waiting was enabled, `_wait_for_order` will have updated `self.runner.resource`.
        return self.runner.resource

    def _wait_for_order(self, order_uuid: str):
        """
        Polls a marketplace order's status until it reaches a terminal state.
        This is a private helper method for the command's execution logic.
        """
        timeout = self.runner.module.params.get("timeout", 600)
        interval = self.runner.module.params.get("interval", 20)
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Use the runner's send_request method to poll the API.
            order, _ = self.runner.send_request(
                "GET", f"/api/marketplace-orders/{order_uuid}/"
            )

            if order and order["state"] == "done":
                # Upon completion, use the runner's check_existence method to fetch
                # the final state of the newly provisioned resource. This updates
                # self.runner.resource, which will be the return value of execute().
                self.runner.check_existence()
                return
            if order and order["state"] in ["erred", "rejected", "canceled"]:
                self.runner.module.fail_json(
                    msg=f"Order finished with status '{order['state']}'. Error message: {order.get('error_message')}"
                )
                return  # Unreachable

            time.sleep(interval)

        self.runner.module.fail_json(
            msg=f"Timeout waiting for order {order_uuid} to complete."
        )

    def to_diff(self) -> Dict[str, Any]:
        """
        Generates a diff showing the order that will be submitted.
        """
        return {
            "state": "Resource will be created via a new marketplace order.",
            "order_attributes": self.order_payload.get("attributes", {}),
        }
