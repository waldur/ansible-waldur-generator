from copy import deepcopy
from typing import Any
from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.helpers import ValidationErrorCollector
from ansible_waldur_generator.interfaces.parser import BaseConfigParser
from ansible_waldur_generator.plugins.crud.config import (
    ModuleIdempotencySection,
    ModuleResolver,
    CrudModuleConfig,
)


class CrudConfigParser(BaseConfigParser):
    """
    Parses the generator configuration, normalizes it, and validates it
    against the parsed API specification.
    """

    def __init__(
        self,
        module_key: str,
        config_data: dict[str, Any],
        api_parser: ApiSpecParser,
        collector: ValidationErrorCollector,
    ):
        self.module_key = module_key
        self.config = config_data
        self.api_parser = api_parser
        self.collector = collector

    def parse(self) -> CrudModuleConfig | None:
        # Use a deep copy to prevent modification of original config.
        config = deepcopy(self.config)

        # Build the structured ModuleConfig object directly from the simplified format.
        module_config_obj = self._build_object(self.module_key, config)
        if module_config_obj is None:
            return None

        # Perform validations that require the full object structure.
        self._validate(module_config_obj)
        return module_config_obj

    def _build_object(
        self, module_key: str, config: dict[str, Any]
    ) -> CrudModuleConfig | None:
        """
        Constructs a ModuleConfig dataclass instance from the simplified config format.
        This method links the configuration with the ApiOperation objects.
        """
        # Validate required fields for simplified format
        if "resource_type" not in config or "operations" not in config:
            self.collector.add_error(
                f"Module '{module_key}': Simplified format requires 'resource_type' and 'operations' fields."
            )
            return None

        resource_type = config["resource_type"]
        operations = config["operations"]

        # Validate required operations
        required_ops = ["list", "create", "destroy"]
        for op in required_ops:
            if op not in operations:
                self.collector.add_error(
                    f"Module '{module_key}': Missing required operation '{op}' in 'operations' section."
                )
                return None

        # Build existence check section from list operation
        list_op_id = operations["list"]
        list_api_op = self.api_parser.get_operation(list_op_id)
        if not list_api_op:
            self.collector.add_error(
                f"Module '{module_key}': OperationId '{list_op_id}' for 'list' operation not found in API spec."
            )
            return None

        check_section = ModuleIdempotencySection(
            operationId=list_op_id,
            api_op=list_api_op,
            config={
                "params": [
                    {
                        "name": "name",
                        "type": "str",
                        "required": True,
                        "description": f"The name of the {resource_type} to check/create/delete.",
                        "maps_to": "name_exact",
                    }
                ]
            },
        )

        # Build create section
        create_op_id = operations["create"]
        create_api_op = self.api_parser.get_operation(create_op_id)
        if not create_api_op:
            self.collector.add_error(
                f"Module '{module_key}': OperationId '{create_op_id}' for 'create' operation not found in API spec."
            )
            return None

        create_section = ModuleIdempotencySection(
            operationId=create_op_id, api_op=create_api_op, config={}
        )

        # Build destroy section
        destroy_op_id = operations["destroy"]
        destroy_api_op = self.api_parser.get_operation(destroy_op_id)
        if not destroy_api_op:
            self.collector.add_error(
                f"Module '{module_key}': OperationId '{destroy_op_id}' for 'destroy' operation not found in API spec."
            )
            return None

        destroy_section = ModuleIdempotencySection(
            operationId=destroy_op_id, api_op=destroy_api_op, config={}
        )

        # Build resolvers, linking them to their ApiOperation objects.
        resolvers = {}
        for name, resolver_conf in config.get("resolvers", {}).items():
            list_op_id = resolver_conf.get("list")
            retrieve_op_id = resolver_conf.get("retrieve")

            if not list_op_id or not retrieve_op_id:
                self.collector.add_error(
                    f"Module '{module_key}', resolver '{name}': Both 'list' and 'retrieve' operationIds are required."
                )
                continue

            list_op = self.api_parser.get_operation(list_op_id)
            retrieve_op = self.api_parser.get_operation(retrieve_op_id)

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

        # Set default description if not provided
        description = config.get(
            "description", f"Manage {resource_type.capitalize()}s in Waldur."
        )

        return CrudModuleConfig(
            module_key=module_key,
            resource_type=resource_type,
            description=description,
            check_section=check_section,
            create_section=create_section,
            destroy_section=destroy_section,
            resolvers=resolvers,
            skip_resolver_check=config.get("skip_resolver_check", []),
        )

    def _validate(self, module_config: CrudModuleConfig):
        """Performs validations that require the fully constructed ModuleConfig object."""
        # Validate that each resolver's list operation supports name-based filtering.
        for name, resolver in module_config.resolvers.items():
            # Both list_op and retrieve_op should exist since we validated them during creation
            if resolver.list_op is None:
                continue

            params = resolver.list_op.raw_spec.get("parameters", [])

            has_name_exact_filter = any(
                p.get("name") == "name_exact" and p.get("in") == "query" for p in params
            )

            if not has_name_exact_filter:
                self.collector.add_error(
                    f"Module '{module_config.module_key}', resolver '{name}': The 'list' operation '{resolver.list_op.operation_id}' must support "
                    f"a 'name_exact' query parameter, but it was not found."
                )
