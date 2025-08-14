from typing import Dict, List, Any

from ansible_waldur_generator.interfaces.builder import BaseContextBuilder
from ansible_waldur_generator.models import AnsibleModuleParams
from ansible_waldur_generator.helpers import AUTH_OPTIONS
from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.plugins.facts.config import FactsModuleConfig


class FactsContextBuilder(BaseContextBuilder):
    """Builds the GenerationContext for a 'facts' module."""

    def __init__(
        self, module_config: FactsModuleConfig, api_parser: ApiSpecParser, collector
    ):
        """
        Initializes the builder. Note that it now accepts the api_parser instance.
        """
        super().__init__(module_config, api_parser, collector)
        self.module_config: FactsModuleConfig = module_config

    def _build_return_block(self) -> Dict[str, Any]:
        # Use the 'retrieve' operation's success response as the source schema.
        return_block = {}
        if self.module_config.retrieve_op:
            retrieve_op_spec = self.module_config.retrieve_op.raw_spec
            return_content = self.return_generator.generate_for_operation(
                retrieve_op_spec
            )

        if return_content:
            # For facts modules, the primary return key is often the pluralized resource type
            # or simply 'resources'. Let's use 'resource' for singular and 'resources' for many.
            if self.module_config.many:
                description = f"A list of dictionaries describing the found {self.module_config.resource_type}s."
                contains_dict = {
                    "description": f"A dictionary describing a single {self.module_config.resource_type}.",
                    "type": "dict",
                    "returned": "always",
                    "contains": return_content,
                }
                return_block = {
                    "resource": {
                        "description": description,
                        "type": "list",
                        "returned": "on success",
                        "elements": "dict",  # Specify that the list contains dictionaries
                        "contains": contains_dict,
                    }
                }
            else:
                description = f"A dictionary describing the found {self.module_config.resource_type}."
                return_type = "dict"
                return_block = {
                    "resource": {
                        "description": description,
                        "type": return_type,
                        "returned": "on success",
                        "contains": return_content,
                    }
                }
        return return_block

    def _build_parameters(self) -> AnsibleModuleParams:
        """Builds parameters based on conventions for a facts module."""
        params = {**AUTH_OPTIONS}  # Include authentication options
        conf = self.module_config

        params[conf.identifier_param] = {
            "name": conf.identifier_param,
            "type": "str",
            "required": not conf.many,
            "description": f"The name or UUID of the {conf.resource_type.replace('_', ' ')}.",
        }
        for p_conf in conf.context_params:
            params[p_conf["name"]] = {
                "name": p_conf["name"],
                "type": "str",
                "required": p_conf.get("required", False),
                "description": p_conf.get("description"),
            }
        return params

    def _build_runner_context(self) -> dict:
        """Builds the context dictionary needed by the FactsRunner."""
        conf = self.module_config

        context_resolvers = {}
        for p_conf in conf.context_params:
            res_conf = p_conf.get("resolver")
            if res_conf:
                list_op = self.api_parser.get_operation(res_conf["list"])
                if list_op:
                    context_resolvers[p_conf["name"]] = {
                        "url": list_op.path,
                        "error_message": f"{p_conf['name'].capitalize()} '{{value}}' not found.",
                        "filter_key": res_conf["filter_key"],
                    }

        return {
            "module_type": "facts",
            "resource_type": conf.resource_type,
            "list_url": conf.list_op.path if conf.list_op else "",
            "retrieve_url": conf.retrieve_op.path if conf.retrieve_op else "",
            "identifier_param": conf.identifier_param,
            "context_resolvers": context_resolvers,
        }

    def _build_examples(
        self,
        module_name: str,
        parameters: AnsibleModuleParams,
        collection_namespace: str,
        collection_name: str,
    ) -> List[Dict[str, Any]]:
        """Builds the EXAMPLES block for a facts module."""

        def get_example_params(param_names):
            params = {
                "access_token": "b83557fd8e2066e98f27dee8f3b3433cdc4183ce",
                "api_url": "https://waldur.example.com:8000/api",
            }
            for p_name in param_names:
                if "project" in p_name:
                    value = "Project Name or UUID"
                elif "name" in p_name:
                    value = (
                        f"{self.module_config.resource_type.capitalize()} Name or UUID"
                    )
                else:
                    value = "some_value"
                params[p_name] = value
            return params

        param_names = list(parameters.keys())
        fqcn = f"{collection_namespace}.{collection_name}.{module_name}"
        task = {
            "name": f"Get a {self.module_config.resource_type.replace('_', ' ')}",
            fqcn: get_example_params(param_names),
        }
        return [
            {
                "name": f"Get a {self.module_config.resource_type.replace('_', ' ')} facts",
                "hosts": "localhost",
                "tasks": [task],
            }
        ]
