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

        # Parse the 'actions' list, inferring the operationId for each action.
        parsed_actions = {}
        # The raw config is expected to have a list of strings for actions.
        for action_name in raw_config.get("actions", []):
            # Infer the operation ID by convention: base_id + _ + action_name
            action_op_id = f"{base_id}_{action_name}"
            operation = api_parser.get_operation(action_op_id)
            if not operation:
                raise ValueError(
                    f"In module '{module_key}', could not find operation with inferred id '{action_op_id}' for action '{action_name}'."
                )
            parsed_actions[action_name] = operation
        # Replace the list in raw_config with the parsed dictionary before validation.
        raw_config["actions"] = parsed_actions

        # Parse resolvers before final validation.
        parsed_resolvers = self._parse_resolvers(raw_config, api_parser)
        raw_config["resolvers"] = parsed_resolvers

        # Validate the configuration using the Pydantic model.
        module_config = ActionsModuleConfig(**raw_config)

        # Perform build-time validation of context parameters against the check operation's schema.
        self._validate_resolvers(
            resolvers=module_config.resolvers,
            api_parser=api_parser,
            module_key=module_key,
            target_operation=module_config.check_operation,
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

        # Add any context parameters from resolvers used for filtering.
        for name, resolver in conf.resolvers.items():
            if resolver.check_filter_key:
                params[name] = {
                    "description": f"The name or UUID of the parent {name} for filtering.",
                    "type": "str",
                    "required": False,
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
        for name, resolver in module_config.resolvers.items():
            if resolver.check_filter_key:
                base_params[name] = f"Parent {name.capitalize()} Name or UUID"

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
        resolvers_data = {}
        check_filter_keys = {}
        for name, resolver in conf.resolvers.items():
            resolvers_data[name] = {
                "url": resolver.list_operation.path if resolver.list_operation else "",
                "error_message": f"{name.capitalize()} '{{value}}' not found.",
            }
            if resolver.check_filter_key:
                check_filter_keys[name] = resolver.check_filter_key

        # Create a simple map of action names to their API endpoint paths.
        actions_map = {name: op.path for name, op in conf.actions.items()}

        return {
            "resource_type": conf.resource_type,
            "check_url": conf.check_operation.path,
            "check_filter_keys": check_filter_keys,
            "retrieve_url": conf.retrieve_operation.path,
            "identifier_param": conf.identifier_param,
            "resolvers": resolvers_data,
            "actions": actions_map,
        }
