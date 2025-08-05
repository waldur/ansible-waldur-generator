"""
Parses and validates the input files (OpenAPI spec, generator config) and
transforms them into structured, typed objects from `generator.models`.
"""

from copy import deepcopy
from typing import Dict, List, Any, Optional

from .models import SdkOperation, ModuleConfig, ModuleIdempotencySection, ModuleResolver
from .helpers import to_snake_case


class ApiSpecParser:
    """Parses an OpenAPI specification into a map of SdkOperation objects."""

    def __init__(self, api_spec_data: Dict[str, Any], collector):
        self.api_spec = api_spec_data
        self.collector = collector
        self.sdk_base_path = "waldur_api_client"

    def parse(self) -> Dict[str, SdkOperation]:
        """
        Main entry point for parsing the API spec.

        Iterates through all paths and operations in the spec, creates an
        SdkOperation object for each, and returns a dictionary mapping
        operationId to the SdkOperation object.

        Returns:
            A dictionary mapping each operationId to its corresponding SdkOperation.
        """
        op_map = {}
        for path, methods in self.api_spec.get("paths", {}).items():
            for method, operation in methods.items():
                op_id = operation.get("operationId")
                if not op_id:
                    self.collector.add_error(
                        f"Operation {method.upper()} {path} is missing 'operationId'."
                    )
                    continue

                tags = operation.get("tags")
                if not tags:
                    self.collector.add_error(f"Operation '{op_id}' is missing 'tags'.")
                    continue

                sdk_operation = self._build_sdk_operation(op_id, tags, operation)
                if sdk_operation:
                    op_map[op_id] = sdk_operation
        return op_map

    def _build_sdk_operation(
        self, op_id: str, tags: List[str], operation: Dict[str, Any]
    ) -> Optional[SdkOperation]:
        """Extracts all relevant information for a single operation."""
        # Convention: the first tag determines the resource and thus the SDK module.
        resource_name = tags[0]

        sdk_module = f"{self.sdk_base_path}.api.{resource_name}"
        sdk_function = op_id

        model_class, model_module, model_schema = None, None, None

        # Check for a requestBody to determine the model information.
        schema_ref = (
            operation.get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema", {})
            .get("$ref")
        )
        if schema_ref:
            model_name = schema_ref.split("/")[-1]
            model_class = model_name
            model_module = f"{self.sdk_base_path}.models.{to_snake_case(model_name)}"
            try:
                model_schema = self._get_schema_by_ref(schema_ref)
            except ValueError as e:
                self.collector.add_error(f"For operation '{op_id}': {e}")
                return None

        return SdkOperation(
            sdk_module=sdk_module,
            sdk_function=sdk_function,
            model_class=model_class,
            model_module=model_module,
            model_schema=model_schema,
            raw_spec=operation,
        )

    def _get_schema_by_ref(self, ref: str) -> Dict[str, Any]:
        """Follows a JSON schema $ref to retrieve the schema definition."""
        parts = ref.lstrip("#/").split("/")
        schema = self.api_spec
        for part in parts:
            schema = schema.get(part)
            if schema is None:
                raise ValueError(
                    f"Invalid $ref, part '{part}' not found in spec: {ref}"
                )
        return schema


class ConfigParser:
    """
    Parses the generator configuration, normalizes it, and validates it
    against the parsed API specification.
    """

    def __init__(
        self, config_data: Dict[str, Any], op_map: Dict[str, SdkOperation], collector
    ):
        self.config = config_data
        self.op_map = op_map
        self.collector = collector

    def parse(self) -> List[ModuleConfig]:
        """
        Main entry point for parsing the generator configuration. It iterates through
        each module definition, normalizes it, builds a structured object,
        and validates it.
        """
        module_configs = []
        for module_key, raw_config in self.config.get("modules", {}).items():
            # Use a deep copy to prevent normalization of one module from affecting another.
            config = deepcopy(raw_config)

            # 1. Expand the simplified config format into the advanced format.
            self._normalize_config(config)

            # 2. Build the structured ModuleConfig object from the normalized dict.
            module_config_obj = self._build_object(module_key, config)
            if module_config_obj:
                # 3. Perform validations that require the full object structure.
                self._validate(module_config_obj)
                module_configs.append(module_config_obj)

        return module_configs

    def _normalize_config(self, config: Dict[str, Any]):
        """
        Expands the simplified `resource_type` format into the more explicit
        advanced format for consistent processing.
        """
        if "resource_type" in config and "operations" in config:
            res_type = config["resource_type"]
            ops = config["operations"]

            if "description" not in config:
                config["description"] = f"Manage {res_type.capitalize()}s in Waldur."

            # This marks it for processing as a standard resource module.
            config["type"] = "resource"

            # Create the explicit 'existence_check' section.
            config["existence_check"] = {
                "operationId": ops["list"],
                "params": [
                    {
                        "name": "name",
                        "type": "str",
                        "required": True,
                        "description": f"The name of the {res_type} to check/create/delete.",
                        "maps_to": "name_exact",
                    }
                ],
            }

            # Create explicit, flattened sections for 'present' and 'absent' actions.
            config["present_create"] = {"operationId": ops["create"]}
            config["absent_destroy"] = {"operationId": ops["destroy"]}

            # Clean up the original simplified keys to avoid confusion.
            del config["operations"]
            if "present" in config:
                del config["present"]
            if "absent" in config:
                del config["absent"]

    def _build_object(
        self, module_key: str, config: Dict[str, Any]
    ) -> Optional[ModuleConfig]:
        """
        Constructs a ModuleConfig dataclass instance from the normalized config dict.
        This method links the configuration with the SdkOperation objects.
        """

        def _get_idempotency_section(
            section_name: str,
        ) -> Optional[ModuleIdempotencySection]:
            """Internal helper to create a ModuleIdempotencySection from a config key."""
            section_data = config.get(section_name, {})
            op_id = section_data.get("operationId")

            if not op_id:
                self.collector.add_error(
                    f"Module '{module_key}': Missing 'operationId' for required section '{section_name}'."
                )
                return None

            sdk_op = self.op_map.get(op_id)
            if not sdk_op:
                self.collector.add_error(
                    f"Module '{module_key}': OperationId '{op_id}' for section '{section_name}' not found in API spec."
                )
                return None

            # Store any other keys (like 'params') in the config attribute.
            specific_config = {
                k: v for k, v in section_data.items() if k != "operationId"
            }

            return ModuleIdempotencySection(
                operationId=op_id, sdk_op=sdk_op, config=specific_config
            )

        # Build the main sections from the now normalized config keys.
        existence_check = _get_idempotency_section("existence_check")
        present_create = _get_idempotency_section("present_create")
        absent_destroy = _get_idempotency_section("absent_destroy")

        # If any of the core sections failed to build, we can't create a valid ModuleConfig.
        if not all([existence_check, present_create, absent_destroy]):
            return None

        # Build resolvers, linking them to their SdkOperation objects.
        resolvers = {}
        for name, resolver_conf in config.get("resolvers", {}).items():
            list_op_id = resolver_conf.get("list")
            retrieve_op_id = resolver_conf.get("retrieve")

            if not list_op_id or not retrieve_op_id:
                self.collector.add_error(
                    f"Module '{module_key}', resolver '{name}': Both 'list' and 'retrieve' operationIds are required."
                )
                continue

            list_op = self.op_map.get(list_op_id)
            retrieve_op = self.op_map.get(retrieve_op_id)

            if not list_op or not retrieve_op:
                self.collector.add_error(
                    f"Module '{module_key}', resolver '{name}': One of the operationIds was not found in API spec."
                )
                continue

            resolvers[name] = ModuleResolver(
                list_op_id=list_op_id,
                retrieve_op_id=retrieve_op_id,
                list_op=list_op,
                retrieve_op=retrieve_op,
                error_message=resolver_conf.get(
                    "error_message", f"{name.capitalize()} '{{value}}' not found."
                ),
            )

        return ModuleConfig(
            module_key=module_key,
            resource_type=config.get("resource_type", module_key),
            description=config.get("description", ""),
            existence_check=existence_check,
            present_create=present_create,
            absent_destroy=absent_destroy,
            resolvers=resolvers,
            skip_resolver_check=config.get("skip_resolver_check", []),
        )

    def _validate(self, module_config: ModuleConfig):
        """Performs validations that require the fully constructed ModuleConfig object."""
        # Validate that each resolver's list operation supports name-based filtering.
        for name, resolver in module_config.resolvers.items():
            params = resolver.list_op.raw_spec.get("parameters", [])

            has_name_exact_filter = any(
                p.get("name") == "name_exact" and p.get("in") == "query" for p in params
            )

            if not has_name_exact_filter:
                self.collector.add_error(
                    f"Module '{module_config.module_key}', resolver '{name}': The 'list' operation '{resolver.list_op.sdk_function}' must support "
                    f"a 'name_exact' query parameter, but it was not found."
                )
