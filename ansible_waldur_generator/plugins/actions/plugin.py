from typing import Any, Dict, List

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.helpers import AUTH_FIXTURE, AUTH_OPTIONS
from ansible_waldur_generator.interfaces.plugin import BasePlugin
from ansible_waldur_generator.models import AnsibleModuleParams
from ansible_waldur_generator.plugins.actions.config import ActionsModuleConfig
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator


class ActionsPlugin(BasePlugin):
    """
    Plugin for generating modules that execute specific, one-off actions on
    an existing resource (e.g., 'reboot', 'connect', 'pull').
    """

    def get_type_name(self) -> str:
        """Returns the unique identifier for this plugin type."""
        return "actions"

    def _parse_configuration(
        self,
        module_key: str,
        raw_config: Dict[str, Any],
        api_parser: ApiSpecParser,
    ) -> ActionsModuleConfig:
        """
        Parses the raw configuration and resolves all operationId strings into
        full ApiOperation objects.
        """
        base_id = raw_config.get("base_operation_id")
        if not base_id:
            raise ValueError(
                f"Module '{module_key}' of type 'actions' requires a `base_operation_id`."
            )

        # Infer the standard check and retrieve operations for finding the resource.
        raw_config["check_operation"] = api_parser.get_operation(f"{base_id}_list")
        raw_config["retrieve_operation"] = api_parser.get_operation(
            f"{base_id}_retrieve"
        )

        if not raw_config["check_operation"] or not raw_config["retrieve_operation"]:
            raise ValueError(
                f"Could not infer list/retrieve operations for base '{base_id}' in module '{module_key}'."
            )

        # Parse the 'actions' dictionary, resolving each operationId.
        parsed_actions = {}
        for action_name, action_op_id in raw_config.get("actions", {}).items():
            operation = api_parser.get_operation(action_op_id)
            if not operation:
                raise ValueError(
                    f"In module '{module_key}', could not find operation with id '{action_op_id}' for action '{action_name}'."
                )
            parsed_actions[action_name] = operation
        raw_config["actions"] = parsed_actions

        # Validate the configuration using the Pydantic model.
        module_config = ActionsModuleConfig(**raw_config)

        # Perform build-time validation of context parameters against the check operation's schema.
        self._validate_context_params(
            module_key=module_key,
            context_params=module_config.context_params,
            target_operation=module_config.check_operation,
            api_parser=api_parser,
        )

        return module_config

    def _build_parameters(
        self, module_config: ActionsModuleConfig, api_parser: ApiSpecParser
    ) -> AnsibleModuleParams:
        """Constructs the dictionary of parameters for the Ansible module."""
        params: AnsibleModuleParams = {**AUTH_OPTIONS}
        conf = module_config

        # Add the primary identifier for the target resource.
        params[conf.identifier_param] = {
            "description": f"The name or UUID of the {conf.resource_type} to perform an action on.",
            "type": "str",
            "required": True,
        }

        # Add the main 'action' parameter with choices derived from the configuration.
        action_choices = list(conf.actions.keys())
        params["action"] = {
            "description": "The action to perform on the resource.",
            "type": "str",
            "required": True,
            "choices": action_choices,
        }

        # Add any context parameters used for filtering the resource search.
        for p_conf in conf.context_params:
            params[p_conf.name] = {
                "description": p_conf.description
                or f"The name or UUID of the parent {p_conf.name} for filtering.",
                "type": "str",
                "required": p_conf.required,
            }
        return params

    def _build_return_block(
        self,
        module_config: ActionsModuleConfig,
        return_generator: ReturnBlockGenerator,
    ) -> Dict[str, Any]:
        """
        Builds the RETURN block to document the data returned on success.
        The structure is based on the 'retrieve' operation's response schema.
        """
        retrieve_op_spec = module_config.retrieve_operation.raw_spec
        return_content = return_generator.generate_for_operation(
            retrieve_op_spec, module_config.resource_type
        )

        if not return_content:
            return {}

        return {
            "resource": {
                "description": f"A dictionary describing the {module_config.resource_type} after the action was performed.",
                "type": "dict",
                "returned": "on success",
                "contains": return_content,
            }
        }

    def _build_examples(
        self,
        module_config: ActionsModuleConfig,
        module_name: str,
        collection_namespace: str,
        collection_name: str,
        schema_parser: ReturnBlockGenerator,
    ) -> List[Dict[str, Any]]:
        """Generates a list of examples, one for each configured action."""
        fqcn = f"{collection_namespace}.{collection_name}.{module_name}"
        examples = []

        # Define the base parameters that are common to all examples.
        base_params = {
            module_config.identifier_param: f"My-Target-{module_config.resource_type.replace(' ', '-')}",
            **AUTH_FIXTURE,
        }
        for p in module_config.context_params:
            base_params[p.name] = f"Parent {p.name.capitalize()} Name or UUID"

        # Create a distinct example for each available action.
        for action_name in module_config.actions.keys():
            example_params = {**base_params, "action": action_name}
            examples.append(
                {
                    "name": f"Perform '{action_name}' action on a {module_config.resource_type}",
                    "hosts": "localhost",
                    "tasks": [{"name": f"Trigger {action_name}", fqcn: example_params}],
                }
            )

        return examples

    def _build_runner_context(
        self, module_config: ActionsModuleConfig, api_parser: ApiSpecParser
    ) -> dict:
        """Assembles the context dictionary for the ActionsRunner."""
        conf = module_config

        # Build the resolver configurations for any context parameters.
        resolvers = {}
        for p_conf in conf.context_params:
            if p_conf.name not in resolvers:
                resolver_base_id = p_conf.resolver
                list_op = api_parser.get_operation(f"{resolver_base_id}_list")
                if list_op:
                    resolvers[p_conf.name] = {
                        "url": list_op.path,
                        "error_message": f"{p_conf.name.capitalize()} '{{value}}' not found.",
                        "filter_key": p_conf.filter_key,
                    }

        # Create a simple map of action names to their API endpoint paths.
        actions_map = {name: op.path for name, op in conf.actions.items()}

        return {
            "resource_type": conf.resource_type,
            "check_url": conf.check_operation.path,
            "retrieve_url": conf.retrieve_operation.path,
            "identifier_param": conf.identifier_param,
            "resolvers": resolvers,
            "actions": actions_map,
        }
