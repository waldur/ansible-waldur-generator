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

    def parse(self) -> CrudModuleConfig:
        # Use a deep copy to prevent normalization of one module from affecting another.
        config = deepcopy(self.config)

        # 1. Expand the simplified config format into the advanced format.
        self._normalize_config(config)

        # 2. Build the structured ModuleConfig object from the normalized dict.
        module_config_obj = self._build_object(self.module_key, config)
        # 3. Perform validations that require the full object structure.
        self._validate(module_config_obj)
        return module_config_obj

    def _normalize_config(self, config: dict[str, Any]):
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
        self, module_key: str, config: dict[str, Any]
    ) -> CrudModuleConfig:
        """
        Constructs a ModuleConfig dataclass instance from the normalized config dict.
        This method links the configuration with the SdkOperation objects.
        """

        def _get_idempotency_section(
            section_name: str,
        ) -> ModuleIdempotencySection | None:
            """Internal helper to create a ModuleIdempotencySection from a config key."""
            section_data = config.get(section_name, {})
            op_id = section_data.get("operationId")

            if not op_id:
                self.collector.add_error(
                    f"Module '{module_key}': Missing 'operationId' for required section '{section_name}'."
                )
                return None

            sdk_op = self.api_parser.get_operation(op_id)
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

        return CrudModuleConfig(
            module_key=module_key,
            resource_type=config.get("resource_type", module_key),
            description=config.get("description", ""),
            existence_check=existence_check,
            present_create=present_create,
            absent_destroy=absent_destroy,
            resolvers=resolvers,
            skip_resolver_check=config.get("skip_resolver_check", []),
        )

    def _validate(self, module_config: CrudModuleConfig):
        """Performs validations that require the fully constructed ModuleConfig object."""
        # Validate that each resolver's list operation supports name-based filtering.
        for name, resolver in module_config.resolvers.items():
            params = resolver.list_op.raw_spec.get("parameters", [])

            has_name_exact_filter = any(
                p.get("name") == "name_exact" and p.get("in") == "query" for p in params
            )

            if not has_name_exact_filter:
                self.collector.add_error(
                    f"Module '{module_config.module_key}', resolver '{name}': The 'list' operation '{resolver.list_op.sdk_function_name}' must support "
                    f"a 'name_exact' query parameter, but it was not found."
                )
