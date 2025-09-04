from ansible_waldur_generator.interfaces.command import Command
from ansible_waldur_generator.interfaces.resolver import ParameterResolver
from ansible_waldur_generator.interfaces.runner import BaseRunner


class ActionsRunner(BaseRunner):
    """
    Runner for modules that execute specific actions on an existing resource.
    This runner inherits from BaseRunner to reuse helpers like `send_request`
    and `check_existence`, but overrides the main `run` method to implement a
    custom workflow that does not use the concept of 'state'.
    """

    def __init__(self, module, context):
        super().__init__(module, context)
        # The resolver is needed to handle any context parameters for finding the resource.
        self.resolver = ParameterResolver(self)

    # The following abstract methods must be implemented to satisfy the BaseRunner
    # contract, but they are not used by this runner's custom `run` method.
    def plan_creation(self) -> list:
        return []

    def plan_update(self) -> list:
        return []

    def plan_deletion(self) -> list:
        return []

    def run(self):
        """
        The main execution workflow for an 'actions' module.
        """
        # 1. Find the target resource using the generic existence check logic.
        self.check_existence()

        # 2. If the resource is not found, fail the module with a clear message.
        if not self.resource:
            identifier = self.module.params.get(self.context["identifier_param"])
            self.module.fail_json(
                msg=f"{self.context['resource_type'].capitalize()} '{identifier}' not found."
            )
            return

        # 3. Get the requested action from the module parameters.
        action_name = self.module.params["action"]
        action_path = self.context["actions"].get(action_name)

        if not action_path:
            self.module.fail_json(
                msg=f"Invalid action '{action_name}'. Supported actions are: {list(self.context['actions'].keys())}"
            )
            return

        # 4. Build a Command object to represent the API call for the action.
        command = Command(
            self,
            method="POST",
            path=action_path,
            command_type="action",
            path_params={"uuid": self.resource["uuid"]},
            description=f"Execute action '{action_name}' on {self.context['resource_type']}",
        )

        # 5. Handle Ansible's check mode.
        if self.module.check_mode:
            self.has_changed = True
            # In check mode, we exit with the planned command without executing it.
            self.exit(plan=[command])
            return

        # 6. Execute the action by making the API call.
        command.execute()
        self.has_changed = True

        # 7. Re-fetch the resource to return its state after the action has been performed.
        self.check_existence()

        # 8. Exit successfully, reporting the change, the command executed, and the final resource state.
        self.exit(plan=[command])
