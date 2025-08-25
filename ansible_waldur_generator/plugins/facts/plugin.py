#
# This file contains the implementation for the 'facts' plugin.
#
# The primary purpose of this plugin is to generate read-only Ansible modules
# that fetch information about existing resources in Waldur. These modules
# are analogous to Ansible's built-in '_facts' modules (e.g., 'setup_facts').
# They never change the state of the system; their sole function is to gather and
# return data.
#
# This implementation reflects all the latest design principles:
# - Inference of 'check' and 'retrieve' operations from a `base_operation_id`.
# - Support for resolver shorthands (e.g., `resolver: "openstack_tenants"`).
# - Generation of high-quality documentation, examples, and runner context.
#

from typing import Any, Dict, List

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.helpers import AUTH_OPTIONS
from ansible_waldur_generator.interfaces.plugin import BasePlugin
from ansible_waldur_generator.models import AnsibleModuleParams
from ansible_waldur_generator.plugins.facts.config import FactsModuleConfig
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator


class FactsPlugin(BasePlugin):
    """
    Plugin for handling the generation of 'facts' modules.
    """

    def get_type_name(self) -> str:
        """
        Returns the unique string identifier for this plugin.
        This name links the plugin to the `plugin: facts` key in the generator config.
        """
        return "facts"

    def _parse_configuration(
        self,
        module_key: str,
        raw_config: Dict[str, Any],
        api_parser: ApiSpecParser,
    ) -> FactsModuleConfig:
        """
        Parses the raw YAML configuration for a single 'facts' module into a
        structured and validated `FactsModuleConfig` object.

        This method embodies the "convention over configuration" principle by
        inferring the required API operations if they are not explicitly defined.
        """
        base_id = raw_config.get("base_operation_id")
        operations_config = raw_config.get("operations", {})

        # --- Operation Inference ---
        # 1. Determine the 'check' (list) operation ID.
        # If an explicit ID is given in the 'operations' block, use it.
        # Otherwise, infer it by appending '_list' to the `base_operation_id`.
        check_op_id = operations_config.get("check")
        if not check_op_id and base_id:
            check_op_id = f"{base_id}_list"

        # 2. Determine the 'retrieve' operation ID using the same logic.
        retrieve_op_id = operations_config.get("retrieve")
        if not retrieve_op_id and base_id:
            retrieve_op_id = f"{base_id}_retrieve"

        # 3. Use the API parser to convert the operation IDs into full ApiOperation objects.
        # These objects contain all the necessary details (path, method, schema) for generation.
        if check_op_id:
            raw_config["list_operation"] = api_parser.get_operation(check_op_id)
        if retrieve_op_id:
            raw_config["retrieve_operation"] = api_parser.get_operation(retrieve_op_id)

        # 4. Instantiate the Pydantic model, which validates the final structure.
        return FactsModuleConfig(**raw_config)

    def _build_parameters(
        self, module_config: FactsModuleConfig, api_parser: ApiSpecParser
    ) -> AnsibleModuleParams:
        """
        Constructs the dictionary of parameters that the generated Ansible module will accept.
        """
        # Start with the standard, required authentication parameters.
        params: AnsibleModuleParams = {**AUTH_OPTIONS}
        conf = module_config

        # Add the primary identifier for the resource (e.g., 'name').
        # This parameter is optional if `many: true`, as the user might want to
        # fetch all resources without specifying a name.
        params[conf.identifier_param] = {
            "description": f"The name or UUID of the {conf.resource_type}.",
            "type": "str",
            "required": not conf.many,
        }

        # Add any context parameters used for filtering (e.g., 'tenant', 'project').
        # These allow the user to narrow the search scope.
        for p_conf in conf.context_params:
            params[p_conf.name] = {
                "description": p_conf.description
                or f"The name or UUID of the parent {p_conf.name}.",
                "type": "str",
                "required": p_conf.required,
            }
        return params

    def _build_return_block(
        self,
        module_config: FactsModuleConfig,
        return_generator: ReturnBlockGenerator,
    ) -> Dict[str, Any]:
        """
        Builds the `RETURN` block for the module's documentation. This section
        describes the data structure that the module returns on success.
        """
        # The 'retrieve' operation is the source of truth for the structure of a
        # single resource, so we use its response schema to generate the documentation.
        if not module_config.retrieve_operation:
            return {}

        retrieve_op_spec = module_config.retrieve_operation.raw_spec
        # The return_generator intelligently parses the OpenAPI schema and builds
        # the documentation structure, including types, descriptions, and sample values.
        return_content = return_generator.generate_for_operation(
            retrieve_op_spec, module_config.resource_type
        )

        if not return_content:
            return {}

        return {
            "resource": {
                "description": f"A list of dictionaries, where each dictionary represents a {module_config.resource_type}.",
                "type": "list",
                "returned": "always",
                "elements": "dict",
                "contains": return_content,  # Describes the structure of a single item in the list.
            }
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
        Constructs a realistic, user-friendly example for the module's documentation.
        """
        # To generate a good example, we first create a "virtual schema" that
        # represents the module's input parameters.
        virtual_schema_props = {
            module_config.identifier_param: {"type": "string"},
            **{p.name: {"type": "string"} for p in module_config.context_params},
        }
        virtual_schema = {"type": "object", "properties": virtual_schema_props}

        # Use the schema parser to generate a sample payload from our virtual schema.
        example_params = schema_parser.generate_example_from_schema(
            virtual_schema,
            module_config.resource_type,
            # We pass the resolver keys so the generator creates helpful placeholders
            # instead of concrete values for these parameters.
            resolver_keys=[p.name for p in module_config.context_params],
        )

        # Replace the auto-generated identifier with a more instructive placeholder.
        example_params[module_config.identifier_param] = "My Resource Name"

        # Add standard authentication parameters to the example.
        example_params.update(
            {
                "access_token": "b83557fd8e2066e98f27dee8f3b3433cdc4183ce",
                "api_url": "https://waldur.example.com",
            }
        )

        # Construct the final playbook example, demonstrating best practices like
        # using the Fully Qualified Collection Name (FQCN), registering the result,
        # and using the debug module to inspect the output.
        fqcn = f"{collection_namespace}.{collection_name}.{module_name}"
        resource_key_plural = module_config.resource_type.replace(" ", "_") + "s"

        return [
            {
                "name": f"Retrieve and print facts about {module_config.resource_type}s",
                "hosts": "localhost",
                "tasks": [
                    {
                        "name": f"Get facts about a specific {module_config.resource_type}",
                        fqcn: example_params,
                        "register": "resource_info",
                    },
                    {
                        "name": "Print the retrieved resource facts",
                        "ansible.builtin.debug": {
                            "var": f"resource_info.{resource_key_plural}",
                        },
                    },
                ],
            }
        ]

    def _build_runner_context(
        self, module_config: FactsModuleConfig, api_parser: ApiSpecParser
    ) -> dict:
        """
        Assembles the 'runner_context' dictionary. This context is serialized into
        the generated module and provides the `FactsRunner` with all the necessary
        API details and logic mappings to perform its tasks at runtime.
        """
        conf = module_config

        # Build the resolver configurations that the runner will use to translate
        # user-provided names/UUIDs for context parameters into the filter keys
        # required by the API.
        resolvers = {}
        for p_conf in conf.context_params:
            if p_conf.name not in resolvers:
                # The resolver for a context param needs the list URL of the parent
                # resource and the query parameter key to use for filtering.
                resolver_base_id = p_conf.resolver
                list_op_id = f"{resolver_base_id}_list"
                list_op = api_parser.get_operation(list_op_id)
                if list_op:
                    resolvers[p_conf.name] = {
                        "url": list_op.path,
                        "error_message": f"{p_conf.name.capitalize()} '{{value}}' not found.",
                        "filter_key": p_conf.filter_key,
                    }

        return {
            "resource_type": conf.resource_type,
            # Provide the API paths for listing and retrieving resources.
            "list_url": conf.list_operation.path if conf.list_operation else "",
            "retrieve_url": conf.retrieve_operation.path
            if conf.retrieve_operation
            else "",
            # Tell the runner which parameter holds the main identifier.
            "identifier_param": conf.identifier_param,
            # Pass the fully constructed resolver map.
            "resolvers": resolvers,
            "many": conf.many,
        }
