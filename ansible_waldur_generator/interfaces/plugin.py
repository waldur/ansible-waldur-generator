from graphlib import CycleError, TopologicalSorter
import os
import sys
from abc import ABC, abstractmethod
from typing import Any

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.helpers import AUTH_FIXTURE
from ansible_waldur_generator.models import (
    AnsibleModuleParams,
    ApiOperation,
    GenerationContext,
    PluginModuleResolver,
)
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

    def _get_standard_commands_return_block(self) -> dict[str, Any]:
        """Returns the static documentation block for the 'commands' output."""
        return {
            "description": "A list of HTTP requests that were made (or would be made in check mode) to execute the task.",
            "type": "list",
            "returned": "when changed",
            "elements": "dict",
            "contains": {
                "method": {
                    "description": "The HTTP method used (e.g., POST, PATCH, DELETE).",
                    "type": "str",
                    "sample": "POST",
                },
                "url": {
                    "description": "The fully qualified URL of the API endpoint.",
                    "type": "str",
                    "sample": "https://api.example.com/api/projects/",
                },
                "description": {
                    "description": "A human-readable summary of the command's purpose.",
                    "type": "str",
                    "sample": "Create new project",
                },
                "body": {
                    "description": "The JSON payload sent with the request. Only present for methods with a body.",
                    "type": "dict",
                    "returned": "if applicable",
                    "sample": {"name": "My-Awesome-Project"},
                },
            },
        }

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

        # Augment the return block with the standard 'commands' output documentation
        # for all plugins that can make changes.
        if self.get_type_name() != "facts" and return_block is not None:
            return_block["commands"] = self._get_standard_commands_return_block()

        return GenerationContext(
            argument_spec=self._build_argument_spec(parameters),
            module_filename=f"{module_key}.py",
            documentation=self._build_documentation(
                module_key,
                getattr(module_config, "description", None),
                parameters,
                module_config,
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
            param_spec = {"type": opts["type"]}
            if "choices" in opts and opts["choices"] is not None:
                param_spec["choices"] = opts["choices"]
            if "default" in opts:
                param_spec["default"] = opts["default"]
            if opts.get("no_log", False):
                param_spec["no_log"] = True
            if opts.get("required", False):
                param_spec["required"] = True
            spec[name] = param_spec
        return spec

    def _build_documentation(
        self,
        module_name: str,
        description: str | None,
        parameters: dict[str, Any],
        module_config: any,
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

        if not description:
            if module_name.endswith("_facts"):
                description = f"Get facts about a specific {module_name.replace('_facts', '').replace('_', ' ')}"
            else:
                description = f"Manage {module_name.replace('_', ' ')} resources."

        updatable_fields = []
        # Handle CrudPlugin style configuration (update_config.fields/actions)
        if hasattr(module_config, "update_config") and module_config.update_config:
            if module_config.update_config.fields:
                updatable_fields.extend(module_config.update_config.fields)
            if (
                hasattr(module_config.update_config, "actions")
                and module_config.update_config.actions
            ):
                updatable_fields.extend(
                    [
                        action.param
                        for action in module_config.update_config.actions.values()
                    ]
                )

        # Handle OrderPlugin style configuration (update_fields/update_actions)
        if hasattr(module_config, "update_fields") and module_config.update_fields:
            updatable_fields.extend(module_config.update_fields)
        if hasattr(module_config, "update_actions") and module_config.update_actions:
            updatable_fields.extend(
                [action.param for action in module_config.update_actions.values()]
            )

        full_description = ""

        if updatable_fields:
            # Format the fields with backticks for better readability in Ansible docs.
            fields_str = ", ".join(sorted(list(set(updatable_fields))))
            full_description = (
                f"When the resource already exists, the following fields can be"
                f" updated: {fields_str}."
            )

        return {
            "module": module_name,
            "short_description": description,
            "description": full_description,
            "author": "Waldur Team",
            "options": self._clean_parameters_for_documentation(parameters),
            "requirements": ["python >= 3.11"],
        }

    def _clean_parameters_for_documentation(
        self, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Filter the internal parameter dictionary to include only keys that are
        valid for Ansible's DOCUMENTATION block. This prevents leaking internal
        keys like 'is_resolved' or 'maps_to' into the final output.
        """

        # Define the set of all valid keys for an option in the DOCUMENTATION block.
        VALID_DOC_KEYS = {
            "description",
            "required",
            "type",
            "default",
            "choices",
            "no_log",
            "suboptions",
            "elements",
        }

        # Create a new, clean dictionary for the documentation options.
        cleaned_options = {}
        for name, opts in parameters.items():
            # For each parameter, build a new dict containing only the valid keys.
            clean_opts = {}
            for key, value in opts.items():
                if key in VALID_DOC_KEYS:
                    # Special handling to prevent `choices: null` in the output.
                    if key == "choices" and not value:
                        continue
                    clean_opts[key] = value
            cleaned_options[name] = clean_opts
        return cleaned_options

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
            **AUTH_FIXTURE,
            **base_params,
        }

        # The schema parser now handles placeholder generation for all resolvable
        # fields, including nested ones, by being aware of the resolver keys.
        inferred_payload = schema_parser.generate_example_from_schema(
            create_schema,
            module_config.resource_type,
            resolver_keys=list(getattr(module_config, "resolvers", {}).keys()),
        )
        create_params.update(inferred_payload)

        #  Post-process path parameters, which are not part of the create_schema.
        path_param_maps = getattr(module_config, "path_param_maps", {})
        for _, ansible_param in path_param_maps.get("create", {}).items():
            display_name = ansible_param.replace("_", " ").capitalize()
            create_params[ansible_param] = f"{display_name} name or UUID"

        # --- Delete Example ---
        delete_params = {
            "state": "absent",
            delete_identifier_param: schema_parser._generate_sample_value(
                delete_identifier_param, {}, module_config.resource_type
            ),
            **AUTH_FIXTURE,
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

        It correctly handles:
        - Direct `enum` fields.
        - Complex `oneOf` or `allOf` constructs that reference other schemas.
        - **Arrays of enums**, by inspecting the `items` schema.

        Args:
            prop_schema: The OpenAPI schema for a single property.
            api_parser: The shared API parser for resolving `$ref`s.

        Returns:
            A list of choice strings, or None if no choices are found.
        """
        if prop_schema.get("type") == "array" and "items" in prop_schema:
            prop_schema = prop_schema["items"]

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
        # Handle 'allOf' for schema composition, which is common for enums with defaults.
        elif "allOf" in prop_schema:
            for sub_schema in prop_schema["allOf"]:
                if "$ref" in sub_schema:
                    try:
                        target_schema = api_parser.get_schema_by_ref(sub_schema["$ref"])
                        if "enum" in target_schema:
                            choices.extend(target_schema["enum"])
                    except (ValueError, KeyError):
                        pass

        return [c for c in choices if c is not None] or None

    def _build_update_actions_context(
        self,
        actions_config: dict[str, Any],
        api_parser: ApiSpecParser,
    ) -> dict[str, Any]:
        """
        A shared utility to build the runner context for complex, action-based updates.

        This method is a critical part of the generator's "intelligence." It acts as a
        bridge between the user's high-level configuration and the low-level metadata
        required by the `BaseRunner` to execute updates correctly and idempotently.

        For each update action defined in the `generator_config.yaml`, this method
        introspects the corresponding API operation's schema in `waldur_api.yaml`
        to infer three key pieces of metadata:

        1.  `idempotency_keys`: For actions that operate on a list of complex objects (e.g.,
            updating a VM's network ports), this determines which fields within each
            object define its unique identity. This is the cornerstone of the robust,
            order-insensitive idempotency check in the runner. For a port, this might
            be `['subnet', 'fixed_ips']`.

        2.  `wrap_in_object`: It determines the expected format of the API request body.
            - `True`: The API expects a JSON object with the parameter name as a key,
              e.g., `{"rules": [...]}`.
            - `False`: The API expects the raw value as the entire request body,
              e.g., just `[...]`.

        3.  `compare_key`: It standardizes the name of the field on the existing resource
            that should be used for the idempotency comparison.

        By centralizing this complex schema analysis here, we keep the plugin-specific
        code clean and ensure that all generated modules, regardless of type, benefit
        from the same robust logic.

        Args:
            actions_config: The dictionary of action configurations from the parsed
                            module config (e.g., `module_config.update_config.actions`).
            api_parser: The shared ApiSpecParser instance, used to access the OpenAPI spec.

        Returns:
            A dictionary formatted for the 'update_actions' key in the `runner_context`.
            This dictionary contains all the pre-processed metadata the runner needs.
        """
        # This dictionary will be populated with the final, processed context for each action.
        update_actions_context = {}

        # We use a ReturnBlockGenerator instance here primarily for its powerful
        # `_resolve_schema` helper method, which can flatten complex schemas by
        # handling `$ref` and `allOf` constructs. This is essential for correctly
        # introspecting the schema of an action's request body.
        schema_resolver = ReturnBlockGenerator(api_parser.api_spec)

        # Iterate through each action defined in the user's configuration.
        for action_name, action in actions_config.items():
            # Get the full OpenAPI schema for the action's request body.
            # Default to an empty dict if no schema is defined.
            # Get the raw, unresolved schema for the action's request body.
            action_schema_raw = action.operation.model_schema or {}

            # This will hold the list of keys to be used for the idempotency check.
            idempotency_keys = []

            defaults_map = {}  # Initialize a map for default values.

            # The name of the Ansible parameter that triggers this action.
            # We use `getattr` for safety, in case the action config object is malformed.
            param_name = getattr(action, "param", None)
            if not param_name:
                continue  # Skip actions that don't specify a parameter.

            # --- Start of Idempotency Key Inference ---
            # This is the core intelligence of the method. We dive into the schema
            # to figure out how to compare lists of objects.

            payload_schema_raw = None
            is_wrapped = False

            if action_schema_raw.get("type") == "array":
                # Case 1: The entire request body is the array (e.g., `set_rules`).
                payload_schema_raw = action_schema_raw
                is_wrapped = False
            elif action_schema_raw.get("type") == "object":
                # Case 2: The request body is an object containing our parameter.
                payload_schema_raw = action_schema_raw.get("properties", {}).get(
                    param_name
                )
                is_wrapped = True

            if payload_schema_raw and payload_schema_raw.get("type") == "array":
                # Get the schema for the items *within* the array.
                item_schema_ref = payload_schema_raw.get("items", {})

                # We must work with the UNRESOLVED schema here.
                # We only resolve a single level of '$ref' if it exists, but we explicitly
                # DO NOT resolve 'allOf'. This ensures we only get the properties
                # that are defined for the *input* of the action.
                item_schema = item_schema_ref
                if "$ref" in item_schema_ref:
                    item_schema = (
                        schema_resolver._get_schema_by_ref(item_schema_ref["$ref"])
                        or {}
                    )

                if item_schema.get("type") == "object":
                    # The idempotency keys are the properties explicitly defined
                    # in this input schema.
                    properties = item_schema.get("properties", {})
                    idempotency_keys = list(properties.keys())

                    # Populate the defaults_map.
                    for key, prop_schema in properties.items():
                        if "default" in prop_schema:
                            defaults_map[key] = prop_schema["default"]

            # --- End of Idempotency Key Inference ---

            compare_key = getattr(action, "compare_key", None) or param_name
            maps_to_key = getattr(action, "maps_to", None)

            # Build the final context dictionary for this specific action.
            update_actions_context[action_name] = {
                "path": action.operation.path,
                "param": param_name,
                "compare_key": compare_key,
                "maps_to": maps_to_key,
                "wrap_in_object": is_wrapped,
                # Provide the inferred keys, sorted for deterministic output.
                "idempotency_keys": sorted(idempotency_keys),
                "defaults_map": defaults_map,
            }

        return update_actions_context

    def _parse_resolvers(
        self, raw_config: dict[str, Any], api_parser: ApiSpecParser
    ) -> dict[str, PluginModuleResolver]:
        """
        A shared, reusable method to parse the 'resolvers' section of a module's
        configuration. It handles shorthand and expands all resolver definitions
        into structured PluginModuleResolver objects.
        """
        parsed_resolvers = {}
        for name, resolver_conf in raw_config.get("resolvers", {}).items():
            # Handle shorthand `resolver: "customers"`
            if isinstance(resolver_conf, str):
                resolver_conf = {
                    "list": f"{resolver_conf}_list",
                    "retrieve": f"{resolver_conf}_retrieve",
                }
            # Handle shorthand `resolver: { base: "customers" }`
            elif "base" in resolver_conf:
                base = resolver_conf["base"]
                resolver_conf["list"] = f"{base}_list"
                resolver_conf["retrieve"] = f"{base}_retrieve"

            # Resolve the operation IDs into full ApiOperation objects.
            resolver_conf["list_operation"] = api_parser.get_operation(
                resolver_conf["list"]
            )
            resolver_conf["retrieve_operation"] = api_parser.get_operation(
                resolver_conf["retrieve"]
            )
            # Validate the final structure with the Pydantic model.
            parsed_resolvers[name] = PluginModuleResolver(**resolver_conf)
        return parsed_resolvers

    def _validate_resolvers(
        self,
        resolvers: dict[str, Any],
        api_parser: ApiSpecParser,
        module_key: str,
        target_operation: ApiOperation | None,
    ):
        """
        A shared, reusable method to validate the resolver configurations
        against the OpenAPI schema of their target API operations.
        """
        # --- Validation Part 1: `filter_by` configuration ---
        for resolver_name, resolver_config in resolvers.items():
            if not getattr(resolver_config, "filter_by", None):
                continue

            list_op = getattr(resolver_config, "list_operation", None)
            if not list_op:
                continue

            list_op_id = list_op.operation_id
            valid_query_params = api_parser.get_query_parameters_for_operation(
                list_op_id
            )

            # Ensure that the 'target_key' for a filter is a valid query parameter
            # on the target API endpoint. This prevents runtime errors.
            for filter_config in resolver_config.filter_by:
                target_key = filter_config.target_key
                if target_key not in valid_query_params:
                    raise ValueError(
                        f"Validation Error in module '{module_key}', resolver '{resolver_name}': "
                        f"The specified target_key '{target_key}' is not a valid filter parameter for the list operation '{list_op_id}'. "
                        f"Available filters are: {sorted(list(valid_query_params))}"
                    )

        # --- Validation Part 2: `check_filter_key` configuration ---
        if not target_operation:
            return  # No existence check operation to validate against.

        op_id = target_operation.operation_id
        valid_filters = api_parser.get_query_parameters_for_operation(op_id)

        for resolver_name, resolver_config in resolvers.items():
            if not resolver_config.check_filter_key:
                continue

            filter_key = resolver_config.check_filter_key
            if filter_key not in valid_filters:
                raise ValueError(
                    f"Validation Error in module '{module_key}', resolver '{resolver_name}': "
                    f"The specified check_filter_key '{filter_key}' is not a valid query parameter "
                    f"for the existence check operation '{op_id}'. "
                    f"Available filters are: {sorted(list(valid_filters))}"
                )

    def _get_sorted_resolvers(
        self, resolvers: dict[str, PluginModuleResolver]
    ) -> list[str]:
        """
        Performs a topological sort on a dictionary of resolvers to determine the correct
        resolution order based on their `filter_by` dependencies.
        """
        # Build the dependency graph. The key is the parameter, and the set contains
        # the parameters it depends on. `graphlib` expects {node: {successors}}.
        graph = {name: set() for name in resolvers}
        for name, resolver in resolvers.items():
            if not getattr(resolver, "filter_by", None):
                continue
            for dep in resolver.filter_by:
                source_param = dep.source_param
                # An edge from source to name means 'name' depends on 'source'.
                if source_param in graph:
                    graph[source_param].add(name)

        try:
            ts = TopologicalSorter(graph)
            return list(ts.static_order())
        except CycleError as e:
            raise ValueError(
                f"A circular dependency was detected in the resolvers: {e}"
            )
