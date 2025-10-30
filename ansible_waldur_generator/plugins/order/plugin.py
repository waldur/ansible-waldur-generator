import re
from typing import Dict, Any, List
from graphlib import TopologicalSorter, CycleError

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator
from ansible_waldur_generator.models import AnsibleModuleParams
from ansible_waldur_generator.helpers import (
    AUTH_FIXTURE,
    AUTH_OPTIONS,
    OPENAPI_TO_ANSIBLE_TYPE_MAP,
    WAITER_OPTIONS,
    capitalize_first,
)
from ansible_waldur_generator.interfaces.plugin import BasePlugin
from ansible_waldur_generator.plugins.order.config import (
    ParameterConfig,
    OrderModuleConfig,
    UpdateActionConfig,
)


class OrderPlugin(BasePlugin):
    """
    The generator plugin for creating Ansible modules that manage resources
    via Waldur's asynchronous marketplace order workflow.

    This is the most powerful plugin, designed to handle:
    - Asynchronous resource provisioning (`state: present`).
    - Direct, synchronous resource updates (`state: present` on existing resource).
    - Asynchronous resource termination (`state: absent`).
    - Automatic inference of module parameters from the offering type schema.
    - Complex parameter resolution, including dependent filters and lists of
      resolvable items (e.g., security groups for a VM).
    """

    def get_type_name(self) -> str:
        """Returns the unique identifier for this plugin type."""
        return "order"

    def _build_return_block(
        self,
        module_config: OrderModuleConfig,
        return_generator: ReturnBlockGenerator,
    ) -> Dict[str, Any]:
        """
        Constructs the RETURN block for the module's documentation.

        It uses the `existence_check_op` as the source of truth for the returned
        data structure, as this operation reflects the final, stable state of
        the provisioned resource.
        """
        return_content = None
        # The success response of the existence check operation (e.g., `openstack_volumes_list`)
        # accurately represents the data structure of the final resource.
        if module_config.existence_check_op:
            existence_check_op_spec = module_config.existence_check_op.raw_spec
            return_content = return_generator.generate_for_operation(
                existence_check_op_spec
            )

        return_block_dict = {}
        if return_content:
            return_block_dict = {
                "resource": {
                    "description": f"A dictionary describing the {module_config.resource_type} after a successful 'present' state.",
                    "type": "dict",
                    "returned": "on success when state is 'present'",
                    "contains": return_content,
                }
            }
        return return_block_dict

    def _build_spec_for_param(
        self,
        p_conf: ParameterConfig,
        api_parser: ApiSpecParser,
        module_config: OrderModuleConfig,
    ) -> dict:
        """
        Recursively builds the `argument_spec` dictionary for a single parameter.

        This powerful helper function translates the plugin's internal `ParameterConfig`
        model into the dictionary structure required by Ansible's documentation and
        `argument_spec`. It handles nested objects (`suboptions`), lists (`elements`),
        and resolves schema references (`$ref`) to build a complete definition.
        """
        p_conf_to_process = p_conf

        # --- Step 1: Resolve Schema References (`$ref`) ---
        # If the parameter is defined by a reference, we fetch the referenced schema
        # and create a new, fully populated ParameterConfig from it. This allows
        # for schema composition and reuse.
        if p_conf.ref:
            ref_path = p_conf.ref
            resolved_schema_dict = api_parser.get_schema_by_ref(ref_path)
            p_conf_to_process = self._create_param_config_from_schema(
                name=p_conf.name,
                prop=resolved_schema_dict,
                required_list=[p_conf.name] if p_conf.required else [],
                api_parser=api_parser,
                module_config=module_config,
            )

        param_spec = {}

        # --- Step 2: Determine Ansible Type and Basic Attributes ---
        param_type = OPENAPI_TO_ANSIBLE_TYPE_MAP.get(p_conf_to_process.type, "str")
        param_spec["type"] = param_type
        param_spec["required"] = p_conf_to_process.required
        if p_conf_to_process.choices:
            param_spec["choices"] = p_conf_to_process.choices
        param_spec["description"] = self._get_prop_description(
            p_conf_to_process.name, p_conf_to_process.model_dump(), module_config
        )

        # --- Step 3: Handle Complex Types Recursively ---
        if param_type == "dict" and p_conf_to_process.properties:
            # For a dictionary, we build 'suboptions' by recursing for each property.
            suboptions = {}
            for sub_p_conf in p_conf_to_process.properties:
                suboptions[sub_p_conf.name] = self._build_spec_for_param(
                    sub_p_conf, api_parser, module_config
                )
            if suboptions:
                param_spec["suboptions"] = suboptions

        elif param_type == "list":
            # For lists, we define the type of the items using 'elements'.
            if p_conf_to_process.is_resolved:
                # **CRITICAL**: If this is a list of resolvable items (e.g., security groups),
                # the user provides a simple list of strings (names/UUIDs). The runner
                # will handle the conversion to the complex API structure.
                param_spec["elements"] = "str"
            elif p_conf_to_process.items:
                # If it's a list of non-resolvable, complex objects (e.g., firewall rules),
                # we recurse to build the full spec for the items, which may include 'suboptions'.
                item_spec = self._build_spec_for_param(
                    p_conf_to_process.items, api_parser, module_config
                )
                item_type = item_spec.get("type", "str")
                param_spec["elements"] = item_type
                if item_type == "dict" and "suboptions" in item_spec:
                    param_spec["suboptions"] = item_spec["suboptions"]

        return param_spec

    def _build_parameters(
        self, module_config: OrderModuleConfig, api_parser: ApiSpecParser
    ) -> AnsibleModuleParams:
        """
        Constructs the complete dictionary of parameters for the Ansible module.

        It combines a set of base parameters common to all order modules with
        the resource-specific `attribute_params` that are either manually defined
        or inferred from the offering's OpenAPI schema.
        """
        params: AnsibleModuleParams = {
            **AUTH_OPTIONS,  # Includes 'api_url' and 'access_token'
            **WAITER_OPTIONS,  # Includes 'state', 'wait', 'timeout', 'interval'
        }

        # Add core parameters required for every marketplace order.
        params["name"] = {
            "type": "str",
            "required": True,
            "description": f"The name of the {module_config.resource_type}.",
        }
        params["project"] = {
            "type": "str",
            "required": True,
            "description": "The name or UUID of the project.",
        }

        # Conditionally add the 'customer' parameter if a resolver for it is defined.
        # This makes the feature opt-in and driven by the generator_config.
        if "customer" in module_config.resolvers:
            params["customer"] = {
                "type": "str",
                "required": False,  # It's an optional filter
                "description": "The name or UUID of the customer to filter the project lookup. This is useful when a project name is not unique across all customers.",
            }

        params["offering"] = {
            "type": "str",
            "required": False,  # Required only for creation, validated by runner
            "description": "The name or UUID of the marketplace offering.",
        }
        params["plan"] = {
            "type": "str",
            "required": False,
            "description": "URL of the marketplace plan.",
        }
        if module_config.has_limits:
            params["limits"] = {
                "type": "dict",
                "required": False,
                "description": "Marketplace resource limits for limit-based billing.",
            }
        # Add a generic description field, which is common for many resources.
        params["description"] = {
            "type": "str",
            "required": False,
            "description": f"A description for the {module_config.resource_type}.",
        }

        # Add any context parameters from resolvers used for filtering the existence check.
        for name, resolver in module_config.resolvers.items():
            if resolver.check_filter_key:
                if name not in params:
                    params[name] = {
                        "description": f"The name or UUID of the parent {name} for filtering.",
                        "type": "str",
                        "required": False,
                    }

        # Determine the set of updatable parameters.
        updatable_params = set(module_config.update_fields)
        updatable_params.update(
            action.param for action in module_config.update_actions.values()
        )

        # Augment core parameter documentation.
        core_create_params = {
            "offering": True,  # True means it's required for create
            "project": True,
            "plan": False,
            "limits": False,
            "description": False,
            "name": True,  # Name is handled separately but check for immutability
        }
        for name, is_required_for_create in core_create_params.items():
            if name in params:
                desc = params[name]["description"]
                desc_list = [desc] if isinstance(desc, str) else desc or []
                if is_required_for_create:
                    desc_list.append("Required when C(state) is 'present'.")
                if name not in updatable_params:
                    desc_list.append("This attribute cannot be updated.")

                unique_desc = list(dict.fromkeys(desc_list))
                params[name]["description"] = (
                    unique_desc[0] if len(unique_desc) == 1 else unique_desc
                )

        # Iterate through all configured attribute parameters.
        for p_conf in module_config.attribute_params:
            param_spec = self._build_spec_for_param(p_conf, api_parser, module_config)

            current_desc = param_spec.get("description", "")
            desc_list = (
                [current_desc] if isinstance(current_desc, str) else current_desc or []
            )

            if p_conf.required:
                desc_list.append("Required when C(state) is 'present'.")
            if p_conf.name not in updatable_params:
                desc_list.append("This attribute cannot be updated.")

            unique_desc = list(dict.fromkeys(desc_list))
            param_spec["description"] = (
                unique_desc[0] if len(unique_desc) == 1 else unique_desc
            )
            param_spec["required"] = False  # Validation is handled by the runner.
            params[p_conf.name] = param_spec

        # Add termination-specific parameters.
        for p_conf in module_config.termination_attributes:
            param_spec = self._build_spec_for_param(p_conf, api_parser, module_config)
            param_spec["required"] = False  # Termination attributes should be optional.
            params[p_conf.name] = param_spec

        return params

    def _build_resolvers(self, module_config: OrderModuleConfig):
        resolvers_data = {}
        params_map = {p.name: p for p in module_config.attribute_params}

        for name, resolver in module_config.resolvers.items():
            param_config = params_map.get(name)
            is_list_resolver = param_config and param_config.type == "array"
            list_item_keys = {}

            # If this resolver is for a list of items (like security_groups),
            # we need to tell the runner how to structure the final payload for each context.
            if is_list_resolver and param_config and param_config.items:
                # 1. Determine the key for the 'create' context (marketplace order)
                if param_config.items.properties:
                    # Infer the key from the nested object's properties (e.g., 'url')
                    if param_config.items.properties:
                        list_item_keys["create"] = param_config.items.properties[0].name

                # 2. Determine the key for the 'update_action' context
                # Find the update action that uses this parameter.
                matching_action = None
                for action in module_config.update_actions.values():
                    if action.param == name:
                        matching_action = action
                        break

                if matching_action:
                    action_schema = matching_action.operation.model_schema
                    if action_schema and name in action_schema.get("properties", {}):
                        param_schema_in_action = action_schema["properties"][name]
                        items_schema = param_schema_in_action.get("items", {})
                        # **THE CRITICAL CHECK**: If the items are simple strings...
                        if (
                            items_schema.get("type") == "string"
                            and "properties" not in items_schema
                        ):
                            list_item_keys["update_action"] = (
                                None  # None signifies a raw list of strings
                            )
                        else:
                            # Handle cases where update also expects objects (less common)
                            item_props = items_schema.get("properties")
                            if item_props:
                                list_item_keys["update_action"] = list(
                                    item_props.keys()
                                )[0]

            resolvers_data[name] = {
                "url": resolver.list_operation.path if resolver.list_operation else "",
                "error_message": resolver.error_message,
                "filter_by": [f.model_dump() for f in resolver.filter_by],
                "is_list": is_list_resolver,
                "list_item_keys": list_item_keys,
            }
        return resolvers_data

    def _get_sorted_attribute_params(
        self, module_config: OrderModuleConfig
    ) -> List[str]:
        """
        Determines the correct order for resolving attribute parameters by performing
        a topological sort on their dependency graph. This prevents runtime errors
        caused by trying to resolve a parameter before its dependencies are ready.

        Returns:
            A list of attribute parameter names in a valid resolution order.

        Raises:
            ValueError: If a circular dependency is detected in the resolvers.
        """
        # 1. Gather all attribute parameters.
        all_params = {p.name for p in module_config.attribute_params}
        all_params.add("description")  # 'description' is a standard attribute

        # 2. Build a dependency graph for parameters that have resolvers.
        # The graph format {node: {successors}} is exactly what graphlib expects.
        resolvers = module_config.resolvers
        all_resolvable_params = {
            name for name in resolvers.keys() if name in all_params
        }
        graph = {name: set() for name in all_resolvable_params}

        for name in all_resolvable_params:
            resolver_config = resolvers[name]
            for dep in resolver_config.filter_by:
                source = dep.source_param
                # An edge exists from the source to the current parameter (source -> name),
                # meaning 'name' depends on 'source'.
                if source in all_resolvable_params:
                    graph[source].add(name)

        # 3. Perform a topological sort using graphlib.
        try:
            ts = TopologicalSorter(graph)
            # The static_order method returns a linear ordering of the nodes.
            sorted_resolvables = list(ts.static_order())
        except CycleError as e:
            # graphlib's CycleError provides a much cleaner way to detect and report cycles.
            raise ValueError(
                f"A circular dependency was detected in the resolvers configuration: {e}"
            )

        # 4. Combine the sorted list of resolvable parameters with the non-resolvable ones.
        non_resolvable_params = sorted(list(all_params - all_resolvable_params))

        # The final, safe processing order is sorted resolvables first, then the rest.
        return sorted_resolvables + non_resolvable_params

    def _get_sorted_resolvers(self, resolvers: Dict[str, Any]) -> List[str]:
        """
        Performs a topological sort on a dictionary of resolvers to determine the correct
        resolution order based on their `filter_by` dependencies.
        """
        graph = {name: set() for name in resolvers}
        for name, resolver in resolvers.items():
            if not getattr(resolver, "filter_by", None):
                continue
            for dep in resolver.filter_by:
                source_param = dep.source_param
                if source_param in graph:
                    graph[source_param].add(name)
        try:
            ts = TopologicalSorter(graph)
            return list(ts.static_order())
        except CycleError as e:
            raise ValueError(
                f"A circular dependency was detected in the resolvers: {e}"
            )

    def _build_runner_context(
        self, module_config: OrderModuleConfig, api_parser
    ) -> Dict[str, Any]:
        """
        Creates the context dictionary that will be passed to the module's runner.
        """
        resolvers = self._build_resolvers(module_config)
        update_actions = {}

        # Use the new shared helper to build the context for update actions.
        if module_config.update_actions:
            update_actions = self._build_update_actions_context(
                module_config.update_actions, api_parser
            )

        # Determine the correct parameter resolution order using a topological sort.
        # This is critical for preventing runtime dependency failures.
        attribute_param_names = self._get_sorted_attribute_params(module_config)

        # Consolidate and sort lists for stable, deterministic output.
        stable_update_fields = sorted(list(dict.fromkeys(module_config.update_fields)))

        termination_attributes_map = {
            p.name: p.maps_to or p.name for p in module_config.termination_attributes
        }

        # Dynamically build the existence check filters from the resolvers.
        check_filter_keys = {}
        for name, resolver in module_config.resolvers.items():
            if resolver.check_filter_key:
                check_filter_keys[name] = resolver.check_filter_key

        # Get the sorted order of resolvers.
        sorted_resolver_names = self._get_sorted_resolvers(module_config.resolvers)

        # A list of attribute parameter names that are required for creation,
        # used for runtime validation by the runner.
        required_for_create = [
            p.name for p in module_config.attribute_params if p.required
        ]
        required_for_create.append("offering")

        runner_context = {
            "resource_type": module_config.resource_type,
            "check_url": module_config.existence_check_op.path
            if module_config.existence_check_op
            else "",
            "check_filter_keys": check_filter_keys,
            "update_url": module_config.update_op.path
            if module_config.update_op
            else None,
            "update_fields": stable_update_fields,
            "attribute_param_names": attribute_param_names,
            "required_for_create": sorted(list(set(required_for_create))),
            "termination_attributes_map": termination_attributes_map,
            "resolvers": resolvers,
            "resolver_order": sorted_resolver_names,
            "update_actions": update_actions,
            # Determine the generic polling path for waiting.
            # Priority 1: The update path IS the detail view.
            # Priority 2: Fall back to the inferred retrieve path.
            "resource_detail_path": (
                module_config.update_op.path
                if module_config.update_op
                else (
                    module_config.retrieve_op.path
                    if module_config.retrieve_op
                    else None
                )
            ),
            "transformations": module_config.transformations,
        }

        if module_config.wait_config:
            runner_context["wait_config"] = module_config.wait_config.model_dump()

        return runner_context

    def _build_schema_for_attributes(
        self, module_config: OrderModuleConfig
    ) -> Dict[str, Any]:
        """
        Constructs a "virtual" JSON schema from the list of attribute parameters.
        This schema is then used by the `ReturnBlockGenerator` to create realistic
        and well-formatted example payloads.
        """
        properties = {}
        properties["name"] = {"type": "string"}
        properties["description"] = {"type": "string"}

        def param_to_prop(p_conf: ParameterConfig):
            """Helper to convert a ParameterConfig back into a schema dictionary."""
            if p_conf.ref:
                return {"$ref": p_conf.ref}

            prop: dict[str, Any] = {"type": p_conf.type}
            if p_conf.type == "array":
                if p_conf.is_resolved:
                    # For a list of names, the example generator should see a list of strings.
                    prop["items"] = {"type": "string"}
                elif p_conf.items:
                    # For a list of complex objects, recurse.
                    prop["items"] = param_to_prop(p_conf.items)
            elif p_conf.properties:
                # For a nested dictionary, recurse on its properties.
                prop["properties"] = {
                    sub.name: param_to_prop(sub) for sub in p_conf.properties
                }
            return prop

        for p_conf in module_config.attribute_params:
            properties[p_conf.name] = param_to_prop(p_conf)

        return {"type": "object", "properties": properties}

    def _build_examples(
        self,
        module_config: OrderModuleConfig,
        module_name: str,
        collection_namespace: str,
        collection_name: str,
        schema_parser: ReturnBlockGenerator,
    ) -> List[Dict[str, Any]]:
        """Builds realistic examples by calling the shared helper from BasePlugin."""
        # Step 1: Construct the virtual schema for the 'attributes' payload.
        attributes_schema = self._build_schema_for_attributes(module_config)
        base_params = {
            "project": "Project Name or UUID",
            "offering": "Offering Name or UUID",
        }

        # Step 2: Call the shared example builder from the base class.
        examples = super()._build_examples_from_schema(
            module_config=module_config,
            module_name=module_name,
            collection_namespace=collection_namespace,
            collection_name=collection_name,
            schema_parser=schema_parser,
            create_schema=attributes_schema,
            base_params=base_params,
            delete_identifier_param="name",
        )

        # Add termination attributes to the delete example.
        if module_config.termination_attributes:
            delete_example_task = examples[-1]["tasks"][0]
            fqcn = list(delete_example_task.keys())[1]
            for term_attr in module_config.termination_attributes:
                sample_prop_schema = {"type": term_attr.type}
                if term_attr.choices:
                    sample_prop_schema["enum"] = term_attr.choices
                delete_example_task[fqcn][term_attr.name] = (
                    schema_parser._generate_sample_value(
                        term_attr.name, sample_prop_schema, module_config.resource_type
                    )
                )

        # Step 3: Add an 'update' example if the module supports it.
        if module_config.update_op and module_config.update_fields:
            update_example_params = {
                "state": "present",
                "name": schema_parser._generate_sample_value(
                    "name", {}, module_config.resource_type
                ),
                "project": "Project Name or UUID",
                **AUTH_FIXTURE,
            }
            # Add the first updatable field to the example for demonstration.
            field_to_update = module_config.update_fields[0]
            update_example_params[field_to_update] = f"An updated {field_to_update}"

            fqcn = f"{collection_namespace}.{collection_name}.{module_name}"
            examples.insert(
                1,  # Insert after the create example
                {
                    "name": f"Update an existing {module_config.resource_type}",
                    "hosts": "localhost",
                    "tasks": [
                        {
                            "name": f"Update the {field_to_update} of a {module_config.resource_type}",
                            fqcn: update_example_params,
                        }
                    ],
                },
            )

        return examples

    def _create_param_config_from_schema(
        self,
        name: str,
        prop: Dict[str, Any],
        required_list: List[str],
        api_parser: ApiSpecParser,
        module_config: OrderModuleConfig,
    ) -> ParameterConfig:
        """
        Recursively creates a structured `ParameterConfig` object from a raw
        OpenAPI schema property. This is the core of schema inference.
        """
        # If the property is a reference, resolve it immediately.
        # This ensures the rest of the function works with a concrete, fully-detailed schema.
        prop_ref = prop.get("$ref")
        if prop_ref:
            try:
                # Replace the current property with the resolved schema.
                prop = api_parser.get_schema_by_ref(prop_ref)
            except ValueError:
                # If ref can't be resolved, return a basic config to avoid crashing.
                return ParameterConfig(
                    name=name,
                    ref=prop_ref,
                    type="object",
                    required=(name in required_list),
                )

        prop_type = prop.get("type")
        if not prop_type and "$ref" in prop:
            prop_type = "object"
        elif not prop_type:
            prop_type = "string"  # A safe default for typeless schemas

        # Recursively parse nested properties for dictionaries.
        sub_properties = []
        if "properties" in prop:
            nested_required = prop.get("required", [])
            for sub_name, sub_prop in prop.get("properties", {}).items():
                if sub_prop.get("readOnly"):
                    continue
                sub_properties.append(
                    self._create_param_config_from_schema(
                        sub_name, sub_prop, nested_required, api_parser, module_config
                    )
                )

        # Recursively parse the item schema for arrays.
        items_config = None
        if "items" in prop and isinstance(prop.get("items"), dict):
            items_config = self._create_param_config_from_schema(
                name="_items_definition",  # Internal name, not user-facing
                prop=prop["items"],
                required_list=[],
                api_parser=api_parser,
                module_config=module_config,
            )

        choices = self._extract_choices_from_prop(prop, api_parser)
        is_resolved = name in module_config.resolvers

        return ParameterConfig(
            name=name,
            type=prop_type,
            format=prop.get("format"),
            required=(name in required_list),
            description=self._get_prop_description(name, prop, module_config),
            is_resolved=is_resolved,
            choices=choices if choices else [],
            ref=prop.get("$ref"),
            properties=sub_properties,
            items=items_config,
        )

    def _get_prop_description(
        self, name: str, prop: Dict[str, Any], module_config
    ) -> str:
        """Generates a user-friendly description for a parameter."""
        description = prop.get("description", "")
        display_name = name.replace("_", " ")
        display_name = re.sub(
            r"\b(ssh|ip|id|url|cpu|ram|vpn|uuid|dns|cidr)\b",
            lambda m: m.group(1).upper(),
            display_name,
            flags=re.IGNORECASE,
        )

        if not description:
            if name in module_config.resolvers:
                description = f"The name or UUID of the {display_name}."
            elif prop.get("format") == "uri":
                description = f"{capitalize_first(display_name)} URL"
            elif prop.get("type") == "array":
                description = f"A list of {display_name} names or UUIDs."
            else:
                description = capitalize_first(display_name)

        # Append transformation details to the description.
        if name in module_config.transformations:
            transform_type = module_config.transformations[name]
            if transform_type == "gb_to_mb":
                # Ensure we don't add a period if there isn't one.
                if not description.endswith("."):
                    description += "."
                description += (
                    " The value should be provided in GiB and will be converted to MiB."
                )

        return description

    def _infer_offering_params(
        self, module_config: OrderModuleConfig, api_parser: ApiSpecParser
    ) -> list[ParameterConfig]:
        """
        Infers attribute parameters automatically from the OpenAPI schema based
        on the configured `offering_type`. This is a key feature that reduces
        manual configuration.
        """
        if not module_config.offering_type:
            return []

        # Construct the expected schema name based on Waldur's convention.
        # e.g., 'OpenStack.Instance' -> 'OpenStackInstanceCreateOrderAttributes'
        schema_name = (
            f"{module_config.offering_type.replace('.', '')}CreateOrderAttributes"
        )
        schema_ref = f"#/components/schemas/{schema_name}"

        try:
            schema = api_parser.get_schema_by_ref(schema_ref)
        except ValueError:
            # The schema for this offering type might not exist in the spec.
            return []

        if not schema or "properties" not in schema:
            return []

        inferred_params = []
        required_fields = schema.get("required", [])

        # Iterate through the schema properties and convert each one to a ParameterConfig object.
        for name, prop in schema.get("properties", {}).items():
            if prop.get("readOnly", False):
                continue
            param = self._create_param_config_from_schema(
                name=name,
                prop=prop,
                required_list=required_fields,
                api_parser=api_parser,
                module_config=module_config,
            )
            inferred_params.append(param)
        return inferred_params

    def _parse_configuration(self, module_key, raw_config, api_parser):
        """
        The main parsing entrypoint for the plugin. It takes the raw config,
        enriches it with inferred data, validates it, and returns a structured
        `OrderModuleConfig` object.
        """
        raw_config.setdefault(
            "resource_type", raw_config["offering_type"].replace(".", " ")
        )
        raw_config.setdefault(
            "description",
            f"Create, update or delete a {raw_config['resource_type']} via the marketplace.",
        )
        base_id = raw_config.get("base_operation_id", "")
        operations_config = raw_config.get("operations", {})

        # --- Step 1: Parse 'check' operation ---
        check_op_conf = operations_config.get("check")
        if check_op_conf is None:
            raw_config["check_op"] = f"{base_id}_list"
        elif isinstance(check_op_conf, str):
            raw_config["check_op"] = check_op_conf

        # Infer retrieve operation, which is used for polling resource state.
        retrieve_op_id = None
        if base_id:
            retrieve_op_id = f"{base_id}_retrieve"

        if retrieve_op_id:
            raw_config["retrieve_op"] = api_parser.get_operation(retrieve_op_id)

        # --- Step 2: Handle the 'update' operation with standardized inference ---
        update_op_conf = operations_config.get("update")
        if update_op_conf is not False:
            update_id = None
            # Priority 1: Explicit ID
            if isinstance(update_op_conf, str):
                update_id = update_op_conf
            elif isinstance(update_op_conf, dict):
                update_id = update_op_conf.get("id")

            # Priority 2: Standard inference
            if not update_id and base_id:
                potential_id = f"{base_id}_partial_update"
                if api_parser.get_operation(potential_id):
                    update_id = potential_id
                else:
                    potential_id = f"{base_id}_update"
                    if api_parser.get_operation(potential_id):
                        update_id = potential_id

            if update_id:
                update_operation = api_parser.get_operation(update_id)
                if update_operation:
                    raw_config["update_op"] = update_operation

                    # Infer fields if not explicitly provided
                    update_fields = None
                    if isinstance(update_op_conf, dict):
                        update_fields = update_op_conf.get("fields")

                    if update_fields is None and update_operation.model_schema:
                        schema = update_operation.model_schema
                        inferred_fields = [
                            name
                            for name, prop in schema.get("properties", {}).items()
                            if not prop.get("readOnly", False)
                            and not prop.get("writeOnly", False)
                        ]
                        raw_config["update_fields"] = inferred_fields
                    elif update_fields is not None:
                        raw_config["update_fields"] = update_fields

        # Parse actions from dict config
        if isinstance(update_op_conf, dict) and "actions" in update_op_conf:
            parsed_actions = {}
            for name, action_conf in update_op_conf["actions"].items():
                action_conf["operation"] = api_parser.get_operation(
                    action_conf["operation"]
                )
                parsed_actions[name] = UpdateActionConfig(**action_conf)
            raw_config["update_actions"] = parsed_actions

        # Handle termination attributes from the 'delete' operation config
        delete_op_conf = operations_config.get("delete")
        if isinstance(delete_op_conf, dict):
            term_attrs_raw = delete_op_conf.get("attributes")
            if isinstance(term_attrs_raw, list):
                parsed_term_attrs = [ParameterConfig(**attr) for attr in term_attrs_raw]
                raw_config["termination_attributes"] = parsed_term_attrs

        # Add default resolvers for 'offering' and 'project', as they
        # are required for every order module.
        raw_config.setdefault("resolvers", {})
        raw_config["resolvers"].setdefault("offering", "marketplace_public_offerings")
        raw_config["resolvers"].setdefault("project", "projects")

        # Convert all operationId strings into full ApiOperation objects.
        raw_config["existence_check_op"] = api_parser.get_operation(
            raw_config["check_op"]
        )
        update_operation = None
        if "update_op" in raw_config:
            update_operation = api_parser.get_operation(raw_config["update_op"])
            raw_config["update_op"] = update_operation

        # Inference Logic for Update Fields
        if update_operation:
            # ...and the update operation has a request body schema...
            if update_operation.model_schema:
                schema = update_operation.model_schema
                # ...infer them from the schema, excluding read-only properties.
                inferred_fields = [
                    name
                    for name, prop in schema.get("properties", {}).items()
                    if not prop.get("readOnly", False)
                    and not prop.get("writeOnly", False)
                ]
                raw_config["update_fields"] = inferred_fields

        # Parse the resolver configurations, expanding shorthand where needed
        parsed_resolvers = self._parse_resolvers(raw_config, api_parser)
        raw_config["resolvers"] = parsed_resolvers

        # Create the initial config object.
        module_config = OrderModuleConfig(**raw_config)

        # Validate resolvers against the existence check operation.
        self._validate_resolvers(
            resolvers=module_config.resolvers,
            api_parser=api_parser,
            module_key=module_key,
            target_operation=module_config.existence_check_op,
        )

        # Infer additional parameters from the offering type schema.
        inferred_params = self._infer_offering_params(module_config, api_parser)

        # Merge inferred params with manually defined params. Manual
        # definitions take precedence, allowing for overrides.
        final_params_dict = {p.name: p for p in inferred_params}
        for manual_param in module_config.attribute_params:
            final_params_dict[manual_param.name] = manual_param
        module_config.attribute_params = list(final_params_dict.values())

        return module_config
