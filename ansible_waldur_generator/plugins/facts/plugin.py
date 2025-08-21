from typing import Dict, Any, List

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator
from ansible_waldur_generator.models import AnsibleModuleParams
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
                    "suboptions": return_content,
                }
                return_block = {
                    "resource": {
                        "description": description,
                        "type": "list",
                        "returned": "on success",
                        "elements": "dict",
                        "suboptions": contains_dict,
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
                        "suboptions": return_content,
                    }
                }
        return return_block

    def _build_parameters(
        self, module_config: FactsModuleConfig, api_parser
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
        collection_namespace: str,
        collection_name: str,
        schema_parser: ReturnBlockGenerator,
    ) -> List[Dict[str, Any]]:
        """
        Builds realistic examples for a facts module using a schema-aware approach.
        """
        # Step 1: Create a "virtual schema" of the module's input parameters.
        virtual_schema_props = {}
        # Add the main identifier parameter (e.g., 'name').
        virtual_schema_props[module_config.identifier_param] = {"type": "string"}
        # Add all context filter parameters (e.g., 'tenant').
        for p_conf in module_config.context_params:
            virtual_schema_props[p_conf.name] = {"type": "string"}

        virtual_schema = {"type": "object", "properties": virtual_schema_props}

        # Step 2: Generate realistic example values from this virtual schema.
        example_params = schema_parser.generate_example_from_schema(
            virtual_schema, module_config.resource_type
        )

        # Step 3: Post-process to replace generated values with more instructive placeholders
        # for the main identifier and any resolved parameters.
        example_params[module_config.identifier_param] = (
            f"{module_config.resource_type.replace('_', ' ').capitalize()} Name or UUID"
        )
        for p_conf in module_config.context_params:
            if p_conf.resolver:
                example_params[p_conf.name] = f"{p_conf.name.capitalize()} Name or UUID"

        # Step 4: Add standard authentication parameters.
        example_params["access_token"] = "b83557fd8e2066e98f27dee8f3b3433cdc4183ce"
        example_params["api_url"] = "https://waldur.example.com"

        # Step 5: Construct the final example, showing best practices like `register` and `debug`.
        fqcn = f"{collection_namespace}.{collection_name}.{module_name}"
        resource_key = module_config.resource_type.replace(" ", "_")

        task_get_facts = {
            "name": f"Get facts about a specific {module_config.resource_type.replace('_', ' ')}",
            fqcn: example_params,
            "register": f"{resource_key}_info",
        }

        task_debug = {
            "name": "Print the retrieved resource facts",
            "ansible.builtin.debug": {
                "var": f"{resource_key}_info.{resource_key}s",
            },
        }

        return [
            {
                "name": f"Retrieve and print facts about {module_config.resource_type.replace('_', ' ')}",
                "hosts": "localhost",
                "tasks": [task_get_facts, task_debug],
            }
        ]

    def _parse_configuration(
        self,
        module_key: str,
        raw_config: Dict[str, Any],
        api_parser: ApiSpecParser,
    ):
        raw_config["list_operation"] = api_parser.get_operation(
            raw_config["list_operation"]
        )
        raw_config["retrieve_operation"] = api_parser.get_operation(
            raw_config["retrieve_operation"]
        )
        return FactsModuleConfig(**raw_config)
