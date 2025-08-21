from abc import ABC, abstractmethod
import os
import sys
from typing import Any

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.models import AnsibleModuleParams, GenerationContext
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator


class BasePlugin(ABC):
    """
    The abstract base class that defines the contract for all generator plugins.

    Each plugin is responsible for a specific type of Ansible module (e.g., 'crud',
    'order', 'facts') and encapsulates the logic for parsing its unique
    configuration, building the module's parameters, and generating the necessary
    documentation and runner context.

    This class also provides shared, concrete helper methods for common tasks
    like building the final Ansible `DOCUMENTATION` block and finding the plugin's
    associated runner file.
    """

    @abstractmethod
    def get_type_name(self) -> str:
        """
        Returns the unique string identifier for this plugin type.

        This name is used in the 'type' field of a module's configuration
        in `generator_config.yaml` to select the correct plugin for generation.

        Returns:
            A string representing the plugin's type (e.g., 'crud').
        """
        ...

    @abstractmethod
    def _parse_configuration(
        self, module_key: str, raw_config: dict[str, Any], api_parser: ApiSpecParser
    ) -> Any:
        """
        Parses the raw dictionary configuration for a module into a structured,
        plugin-specific configuration object (typically a Pydantic model).

        This method is responsible for validating the plugin-specific sections of
        the configuration and resolving any `operationId` strings into full
        `ApiOperation` objects using the `api_parser`.

        Args:
            module_key: The name of the module being generated (e.g., 'project').
            raw_config: The raw dictionary for one module from `generator_config.yaml`.
            api_parser: The shared `ApiSpecParser` instance for resolving API operations.

        Returns:
            A plugin-specific configuration object (e.g., `CrudModuleConfig`).
        """
        ...

    @abstractmethod
    def _build_parameters(
        self, module_config: Any, api_parser: ApiSpecParser
    ) -> AnsibleModuleParams:
        """
        Constructs the dictionary of parameters for the Ansible module.

        This involves combining base parameters (like authentication), parameters
        inferred from the API schema (e.g., from a request body), and any
        parameters defined explicitly in the module's configuration.

        Args:
            module_config: The parsed, plugin-specific configuration object.
            api_parser: The shared `ApiSpecParser` instance, used for schema lookups.

        Returns:
            A dictionary representing the module's `options` for the DOCUMENTATION block.
        """
        ...

    @abstractmethod
    def _build_return_block(
        self,
        module_config: Any,
        return_generator: ReturnBlockGenerator,
    ) -> dict[str, Any]:
        """
        Builds the RETURN block for the module's documentation.

        This method typically identifies the appropriate API operation (e.g., a 'create'
        or 'retrieve' operation) and uses the `return_generator` to create a
        structured representation of the data returned by that operation on success.

        Args:
            module_config: The parsed, plugin-specific configuration object.
            return_generator: The shared `ReturnBlockGenerator` instance.

        Returns:
            A dictionary formatted for Ansible's `RETURN` documentation string.
        """
        ...

    @abstractmethod
    def _build_examples(
        self,
        module_config: Any,
        module_name: str,
        collection_namespace: str,
        collection_name: str,
        schema_parser: ReturnBlockGenerator,
    ) -> list[dict[str, Any]]:
        """
        Constructs a list of example plays for the module's documentation.

        This method should create realistic, helpful examples that demonstrate
        the primary use cases of the module (e.g., creating and deleting a resource).

        Args:
            module_config: The parsed, plugin-specific configuration object.
            module_name: The name of the module file (e.g., 'project').
            collection_namespace: The namespace of the collection (e.g., 'waldur').
            collection_name: The name of the collection (e.g., 'openstack').
            schema_parser: The shared `ReturnBlockGenerator` instance, used for
                           generating realistic example data from schemas.

        Returns:
            A list of dictionaries, where each dictionary represents a complete example play.
        """
        ...

    @abstractmethod
    def _build_runner_context(
        self, module_config: Any, api_parser: ApiSpecParser
    ) -> dict[str, Any]:
        """
        Creates the context dictionary that will be passed to the module's runner.

        This context contains all the necessary, pre-processed information that the
        runner needs to execute its logic, such as API paths, parameter mappings,
        and resolver configurations. This keeps the runner itself generic and
        configurable.

        Args:
            module_config: The parsed, plugin-specific configuration object.
            api_parser: The shared `ApiSpecParser` instance.

        Returns:
            A dictionary that will be serialized into the generated module.
        """
        ...

    def generate(
        self,
        module_key: str,
        raw_config: dict[str, Any],
        api_parser: ApiSpecParser,
        collection_namespace: str,
        collection_name: str,
        return_generator: ReturnBlockGenerator,
    ) -> GenerationContext:
        """
        The main orchestration method for the plugin.

        This concrete method implements the high-level workflow for generating
        a module by calling the abstract builder methods in the correct order.
        It encapsulates the boilerplate of assembling the final `GenerationContext`.

        Args:
            module_key: The name of the module being generated.
            raw_config: The raw dictionary configuration for the module.
            api_parser: The shared API spec parser.
            collection_namespace: The target collection's namespace.
            collection_name: The target collection's name.
            return_generator: The shared documentation and example generator.

        Returns:
            A `GenerationContext` object containing all data needed for template rendering.
        """
        module_config = self._parse_configuration(module_key, raw_config, api_parser)

        parameters = self._build_parameters(module_config, api_parser)
        return_block = self._build_return_block(module_config, return_generator)
        examples = self._build_examples(
            module_config,
            module_key,
            collection_namespace,
            collection_name,
            return_generator,
        )
        runner_context = self._build_runner_context(module_config, api_parser)

        return GenerationContext(
            argument_spec=self._build_argument_spec(parameters),
            module_filename=f"{module_key}.py",
            documentation=self._build_documentation(
                module_key, getattr(module_config, "description", None), parameters
            ),
            examples=examples,
            return_block=return_block,
            runner_context=runner_context,
        )

    def _build_argument_spec(self, parameters: dict[str, Any]) -> dict:
        """
        Constructs the `argument_spec` dictionary for `AnsibleModule` from
        the detailed parameter definitions.

        This method strips down the rich parameter info (which includes descriptions, etc.)
        to the minimal structure required by Ansible's module boilerplate.

        Args:
            parameters: The full parameter dictionary from `_build_parameters`.

        Returns:
            A dictionary suitable for the `argument_spec` argument of `AnsibleModule`.
        """
        spec = {}
        for name, opts in parameters.items():
            param_spec = {"type": opts["type"], "required": opts.get("required", False)}
            if "choices" in opts and opts["choices"] is not None:
                param_spec["choices"] = opts["choices"]
            spec[name] = param_spec
        return spec

    def _build_documentation(
        self,
        module_name: str,
        description: str | None,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Constructs the main `DOCUMENTATION` block for the Ansible module.

        Args:
            module_name: The name of the module.
            description: The short description of the module.
            parameters: The dictionary of module options.

        Returns:
            A dictionary representing the complete `DOCUMENTATION` section.
        """
        processed_description = (
            description or f"Manage {module_name.replace('_', ' ')} resources."
        )
        return {
            "module": module_name,
            "short_description": processed_description,
            "description": [processed_description],
            "author": "Waldur Team",
            "options": parameters,
            "requirements": ["python >= 3.11"],
        }

    def _build_examples_from_schema(
        self,
        module_config: Any,
        module_name: str,
        collection_namespace: str,
        collection_name: str,
        schema_parser: ReturnBlockGenerator,
        create_schema: dict[str, Any],
        base_params: dict[str, Any],
        delete_identifier_param: str = "name",
    ) -> list[dict]:
        """
        Builds realistic EXAMPLES using a hybrid of schema-inferred data
        and context-aware placeholders for resolved parameters.

        This is a shared helper for all plugins to ensure consistent and high-quality
        example generation.

        Args:
            module_config: The parsed, plugin-specific configuration object.
            module_name: The name of the module.
            collection_namespace: The target collection's namespace.
            collection_name: The target collection's name.
            schema_parser: The shared schema parser for generating sample data.
            create_schema: A JSON-schema-like dictionary representing the module's
                           input parameters for a 'create' action.
            base_params: A dictionary of base parameters (like 'project' or 'tenant')
                         that are required for the examples but are not part of the
                         `create_schema`.
            delete_identifier_param: The name of the parameter used to identify
                                     the resource for deletion.

        Returns:
            A list of dictionaries representing complete, realistic example plays.
        """
        fqcn = f"{collection_namespace}.{collection_name}.{module_name}"

        # --- Create Example ---
        create_params = {
            "state": "present",
            "access_token": "b83557fd8e2066e98f27dee8f3b3433cdc4183ce",
            "api_url": "https://waldur.example.com",
            **base_params,
        }

        inferred_payload = schema_parser.generate_example_from_schema(
            create_schema, module_config.resource_type
        )
        create_params.update(inferred_payload)

        path_param_maps = getattr(module_config, "path_param_maps", {})
        for _, ansible_param in path_param_maps.get("create", {}).items():
            create_params[ansible_param] = f"{ansible_param.capitalize()} Name or UUID"

        for resolver_name in getattr(module_config, "resolvers", {}).keys():
            if resolver_name in create_params:
                create_params[resolver_name] = (
                    f"{resolver_name.capitalize()} Name or UUID"
                )

        # --- Delete Example ---
        delete_params = {
            "state": "absent",
            delete_identifier_param: schema_parser._generate_sample_value(
                delete_identifier_param, {}, module_config.resource_type
            ),
            "access_token": "b83557fd8e2066e98f27dee8f3b3433cdc4183ce",
            "api_url": "https://waldur.example.com",
            **base_params,
        }

        return [
            {
                "name": f"Create a new {module_config.resource_type}",
                "hosts": "localhost",
                "tasks": [
                    {"name": f"Add {module_config.resource_type}", fqcn: create_params}
                ],
            },
            {
                "name": f"Remove an existing {module_config.resource_type}",
                "hosts": "localhost",
                "tasks": [
                    {
                        "name": f"Remove {module_config.resource_type}",
                        fqcn: delete_params,
                    }
                ],
            },
        ]

    def get_runner_path(self) -> str | None:
        """
        Discovers and returns the absolute path to the 'runner.py' file
        associated with this plugin.

        It assumes the runner file is located in the same directory as the
        plugin's implementation file.

        Returns:
            The absolute path to the runner file, or None if it doesn't exist.
        """
        module = sys.modules[self.__class__.__module__]
        if not module.__file__:
            return None
        plugin_dir = os.path.dirname(module.__file__)
        runner_path = os.path.join(plugin_dir, "runner.py")
        return runner_path if os.path.exists(runner_path) else None

    def _extract_choices_from_prop(
        self, prop_schema: dict[str, Any], api_parser: ApiSpecParser
    ) -> list[str] | None:
        """
        Extracts a list of enum choices from a property schema.

        It correctly handles both direct `enum` fields and complex `oneOf`
        constructs that reference other schema components containing enums.

        Args:
            prop_schema: The OpenAPI schema for a single property.
            api_parser: The shared API parser for resolving `$ref`s.

        Returns:
            A list of choice strings, or None if no choices are found.
        """
        choices = []
        if "enum" in prop_schema:
            choices.extend(prop_schema["enum"])
        elif "oneOf" in prop_schema:
            for sub_ref in prop_schema["oneOf"]:
                if "$ref" in sub_ref:
                    try:
                        target_schema = api_parser.get_schema_by_ref(sub_ref["$ref"])
                        if "enum" in target_schema:
                            choices.extend(target_schema["enum"])
                    except (ValueError, KeyError):
                        pass  # Suppress errors if a ref can't be resolved
        return [c for c in choices if c is not None] or None
