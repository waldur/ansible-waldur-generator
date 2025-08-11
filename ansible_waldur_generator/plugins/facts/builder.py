import pprint
from typing import Dict, List, Any

from ansible_waldur_generator.interfaces.builder import BaseContextBuilder
from ansible_waldur_generator.models import AnsibleModuleParams
from ansible_waldur_generator.helpers import AUTH_OPTIONS, to_python_code_string
from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.plugins.facts.config import FactsModuleConfig
from ansible_waldur_generator.plugins.facts.context import FactsGenerationContext


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

    def build(
        self, collection_namespace: str, collection_name: str
    ) -> FactsGenerationContext:
        """Main entry point for the builder."""

        parameters = self._build_parameters()
        sdk_imports = self._collect_imports()
        doc_data = self._build_documentation_data(
            self.module_config.module_key,
            parameters,
            collection_namespace,
            collection_name,
        )
        examples_data = self._build_examples_data(
            self.module_config.module_key,
            parameters,
            collection_namespace,
            collection_name,
        )

        runner_context_data = self._build_runner_context_data()
        runner_context_string = to_python_code_string(
            runner_context_data, indent_level=4
        )

        argument_spec_data = self._build_argument_spec_data(parameters)
        argument_spec_string = pprint.pformat(
            argument_spec_data, indent=4, width=120, sort_dicts=False
        )

        runner_import_path = (
            f"ansible_collections.{collection_namespace}.{collection_name}"
            f".plugins.module_utils.waldur.facts_runner"
        )

        # Use the 'retrieve' operation's success response as the source schema.
        retrieve_op_spec = self.module_config.retrieve_op.sdk_op.raw_spec
        return_content = self.return_generator.generate_for_operation(retrieve_op_spec)
        return_block = {}

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

        return FactsGenerationContext(
            module_name=self.module_config.module_key,
            description=self.module_config.description,
            parameters=parameters,
            sdk_imports=sdk_imports,
            documentation=doc_data,
            examples=examples_data,
            resource_type=self.module_config.resource_type,
            runner_class_name="FactsRunner",
            runner_import_path=runner_import_path,
            runner_context_string=runner_context_string,
            argument_spec_string=argument_spec_string,
            return_block=return_block,
        )

    def _build_argument_spec_data(
        self, parameters: AnsibleModuleParams
    ) -> Dict[str, Any]:
        """Constructs the argument_spec dictionary."""
        spec = {**AUTH_OPTIONS}
        for name, opts in parameters.items():
            param_spec = {"type": opts["type"], "required": opts.get("required", False)}
            if opts.get("choices"):
                param_spec["choices"] = opts["choices"]
            spec[name] = param_spec
        return spec

    def _build_parameters(self) -> AnsibleModuleParams:
        """Builds parameters based on conventions for a facts module."""
        params = {}
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

    def _collect_imports(self) -> list:
        """Collects all unique SDK imports needed for this module type."""
        imports = set()
        conf = self.module_config

        # Add the main list and retrieve operations for the resource.
        imports.add(
            (conf.list_op.sdk_op.sdk_module_name, conf.list_op.sdk_op.sdk_function_name)
        )
        imports.add(
            (
                conf.retrieve_op.sdk_op.sdk_module_name,
                conf.retrieve_op.sdk_op.sdk_function_name,
            )
        )

        # Add imports for all context resolvers.
        for p_conf in conf.context_params:
            resolver_conf = p_conf.get("resolver")
            if resolver_conf:
                list_op = self.api_parser.get_operation(resolver_conf["list"])
                retrieve_op = self.api_parser.get_operation(resolver_conf["retrieve"])
                if list_op:
                    imports.add((list_op.sdk_module_name, list_op.sdk_function_name))
                if retrieve_op:
                    imports.add(
                        (retrieve_op.sdk_module_name, retrieve_op.sdk_function_name)
                    )

        return [
            {"module": mod, "function": func} for mod, func in sorted(list(imports))
        ]

    def _build_runner_context_data(self) -> dict:
        """Builds the context dictionary needed by the FactsRunner."""
        conf = self.module_config

        context_resolvers = {}
        for p_conf in conf.context_params:
            res_conf = p_conf.get("resolver")
            if res_conf:
                list_op = self.api_parser.get_operation(res_conf["list"])
                retrieve_op = self.api_parser.get_operation(res_conf["retrieve"])
                if list_op and retrieve_op:
                    context_resolvers[p_conf["name"]] = {
                        "list_func": list_op.sdk_function,
                        "retrieve_func": retrieve_op.sdk_function,
                        "error_message": f"{p_conf['name'].capitalize()} '{{value}}' not found.",
                        "filter_key": res_conf["filter_key"],
                    }

        return {
            "module_type": "facts",
            "resource_type": conf.resource_type,
            "list_func": conf.list_op.sdk_op.sdk_function,
            "retrieve_func": conf.retrieve_op.sdk_op.sdk_function,
            "identifier_param": conf.identifier_param,
            "context_resolvers": context_resolvers,
        }

    def _build_examples_data(
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
