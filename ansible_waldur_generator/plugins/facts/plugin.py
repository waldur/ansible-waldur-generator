from typing import Dict, Any, List

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator
from ansible_waldur_generator.models import (
    GenerationContext,
    AnsibleModuleParams,
)
from ansible_waldur_generator.helpers import AUTH_OPTIONS
from ansible_waldur_generator.interfaces.plugin import BasePlugin
from ansible_waldur_generator.plugins.facts.config import FactsModuleConfig


class FactsPlugin(BasePlugin):
    """Plugin for handling 'facts' module types."""

    def get_type_name(self) -> str:
        return "facts"

    def _build_return_block(
        self, module_config: FactsModuleConfig, return_generator: ReturnBlockGenerator
    ) -> Dict[str, Any]:
        return_block = {}
        if module_config.retrieve_operation:
            retrieve_op_spec = module_config.retrieve_operation.raw_spec
            return_content = return_generator.generate_for_operation(retrieve_op_spec)

        if return_content:
            if module_config.many:
                description = f"A list of dictionaries describing the found {module_config.resource_type}s."
                contains_dict = {
                    "description": f"A dictionary describing a single {module_config.resource_type}.",
                    "type": "dict",
                    "returned": "always",
                    "contains": return_content,
                }
                return_block = {
                    "resource": {
                        "description": description,
                        "type": "list",
                        "returned": "on success",
                        "elements": "dict",
                        "contains": contains_dict,
                    }
                }
            else:
                description = (
                    f"A dictionary describing the found {module_config.resource_type}."
                )
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

    def _build_parameters(
        self, module_config: FactsModuleConfig
    ) -> AnsibleModuleParams:
        params = {**AUTH_OPTIONS}
        conf = module_config

        params[conf.identifier_param] = {
            "name": conf.identifier_param,
            "type": "str",
            "required": not conf.many,
            "description": f"The name or UUID of the {conf.resource_type.replace('_', ' ')}.",
        }
        for p_conf in conf.context_params:
            params[p_conf.name] = {
                "name": p_conf.name,
                "type": "str",
                "required": p_conf.required,
                "description": p_conf.description or "",
            }
        return params

    def _build_runner_context(
        self, module_config: FactsModuleConfig, api_parser: ApiSpecParser
    ) -> dict:
        conf = module_config

        context_resolvers = {}
        for p_conf in conf.context_params:
            res_conf = p_conf.resolver
            if res_conf:
                list_op = api_parser.get_operation(res_conf["list"])
                if list_op:
                    context_resolvers[p_conf.name] = {
                        "url": list_op.path,
                        "error_message": f"{p_conf.name.capitalize()} '{{value}}' not found.",
                        "filter_key": res_conf["filter_key"],
                    }

        return {
            "module_type": "facts",
            "resource_type": conf.resource_type,
            "list_url": conf.list_operation.path if conf.list_operation else "",
            "retrieve_url": (
                conf.retrieve_operation.path if conf.retrieve_operation else ""
            ),
            "identifier_param": conf.identifier_param,
            "context_resolvers": context_resolvers,
        }

    def _build_examples(
        self,
        module_config: FactsModuleConfig,
        module_name: str,
        parameters: AnsibleModuleParams,
        collection_namespace: str,
        collection_name: str,
    ) -> List[Dict[str, Any]]:
        def get_example_params(param_names):
            params = {
                "access_token": "b83557fd8e2066e98f27dee8f3b3433cdc4183ce",
                "api_url": "https://waldur.example.com:8000/api",
            }
            for p_name in param_names:
                if "project" in p_name:
                    value = "Project Name or UUID"
                elif "name" in p_name:
                    value = f"{module_config.resource_type.capitalize()} Name or UUID"
                else:
                    value = "some_value"
                params[p_name] = value
            return params

        param_names = list(parameters.keys())
        fqcn = f"{collection_namespace}.{collection_name}.{module_name}"
        task = {
            "name": f"Get a {module_config.resource_type.replace('_', ' ')}",
            fqcn: get_example_params(param_names),
        }
        return [
            {
                "name": f"Get a {module_config.resource_type.replace('_', ' ')} facts",
                "hosts": "localhost",
                "tasks": [task],
            }
        ]

    def generate(
        self,
        module_key: str,
        raw_config: Dict[str, Any],
        api_parser: ApiSpecParser,
        collection_namespace: str,
        collection_name: str,
        return_generator: ReturnBlockGenerator,
    ) -> GenerationContext:
        """
        Processes a validated configuration to produce the module's documentation and runner context.
        """

        raw_config["list_operation"] = api_parser.get_operation(
            raw_config["list_operation"]
        )
        raw_config["retrieve_operation"] = api_parser.get_operation(
            raw_config["retrieve_operation"]
        )
        module_config = FactsModuleConfig(**raw_config)

        module_name = f"{module_config.resource_type}_info"

        parameters = self._build_parameters(module_config)
        return_block = self._build_return_block(module_config, return_generator)
        examples = self._build_examples(
            module_config,
            module_name,
            parameters,
            collection_namespace,
            collection_name,
        )
        runner_context = self._build_runner_context(module_config, api_parser)

        return GenerationContext(
            argument_spec=self._build_argument_spec(parameters),
            module_filename=f"{module_name}.py",
            documentation={
                "module": module_name,
                "short_description": module_config.description,
                "description": [module_config.description],
                "author": "Waldur Team",
                "options": parameters,
                "requirements": ["python >= 3.11", "requests"],
            },
            examples=examples,
            return_block=return_block,
            runner_context=runner_context,
        )
