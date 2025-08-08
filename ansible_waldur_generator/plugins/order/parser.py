"""
Parses and validates the raw configuration for a module of type 'order'.
"""

from copy import deepcopy
from typing import Any

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.helpers import ValidationErrorCollector
from ansible_waldur_generator.interfaces.parser import BaseConfigParser
from ansible_waldur_generator.plugins.crud.config import (
    ModuleIdempotencySection,
    ModuleResolver,
)
from ansible_waldur_generator.plugins.order.config import OrderModuleConfig


class OrderConfigParser(BaseConfigParser):
    """
    Parses the generator configuration for an 'order' type module,
    validates it against the API spec, and builds a structured OrderModuleConfig object.
    """

    def __init__(
        self,
        module_key: str,
        raw_config: dict[str, Any],
        api_parser: ApiSpecParser,
        collector: ValidationErrorCollector,
    ):
        """Initializes the parser with all necessary context."""
        super().__init__(module_key, raw_config, api_parser, collector)
        # Use a deep copy to prevent modifications from affecting other modules.
        self.config = deepcopy(self.raw_config)

    def parse(self) -> OrderModuleConfig | None:
        """
        The main entry point for the parser. It orchestrates the validation and
        building of the OrderModuleConfig object.

        Returns:
            An instance of OrderModuleConfig if parsing is successful, otherwise None.
        """
        # 1. First, perform a quick check for essential top-level keys.
        if not self._validate_required_keys():
            return None  # Errors have been added to the collector.

        # 2. Build the core operational sections, resolving their operationIds.
        existence_check = self._build_idempotency_section(
            "existence_check_op", is_required=True
        )
        update_op = self._build_idempotency_section("update_op", is_required=False)

        # If the mandatory existence_check section failed to build, we cannot proceed.
        if not existence_check:
            return None

        # 3. Build the dictionary of parameter resolvers.
        resolvers = self._build_resolvers()

        # 4. Construct the final, structured config object.
        return OrderModuleConfig(
            module_key=self.module_key,
            description=self.config.get("description", ""),
            resource_type=self.config.get("resource_type", self.module_key),
            existence_check_op=existence_check,
            update_op=update_op,
            update_check_fields=self.config.get("update_check_fields", []),
            attribute_params=self.config.get("attribute_params", []),
            resolvers=resolvers,
        )

    def _validate_required_keys(self) -> bool:
        """Checks for the presence of mandatory keys in the raw configuration."""
        required_keys = ["existence_check_op", "resource_type"]
        is_valid = True
        for key in required_keys:
            if key not in self.config:
                self.collector.add_error(
                    f"{self.context_str}: Missing required key '{key}'."
                )
                is_valid = False
        return is_valid

    def _build_idempotency_section(
        self, section_key: str, is_required: bool
    ) -> ModuleIdempotencySection | None:
        """
        Builds a ModuleIdempotencySection for a given key (e.g., 'existence_check_op').
        It handles resolving the operationId and gracefully reports errors.
        """
        section_data = self.config.get(section_key)

        if not section_data:
            if is_required:
                # This case is already covered by _validate_required_keys, but serves as a safeguard.
                self.collector.add_error(
                    f"{self.context_str}: Mandatory section '{section_key}' is missing."
                )
            return None

        # The config can be a simple string (the operationId) or a dictionary.
        if isinstance(section_data, str):
            op_id = section_data
            specific_config = {}
        elif isinstance(section_data, dict):
            op_id = section_data.get("operationId")
            specific_config = {
                k: v for k, v in section_data.items() if k != "operationId"
            }
        else:
            self.collector.add_error(
                f"{self.context_str}: Section '{section_key}' must be a string (operationId) or a dictionary."
            )
            return None

        if not op_id:
            self.collector.add_error(
                f"{self.context_str}: Missing 'operationId' in section '{section_key}'."
            )
            return None

        # Use the API parser to resolve the string ID into a full SdkOperation object.
        sdk_op = self.api_parser.get_operation(op_id)
        if not sdk_op:
            self.collector.add_error(
                f"{self.context_str}: OperationId '{op_id}' for section '{section_key}' not found in API spec."
            )
            return None

        return ModuleIdempotencySection(
            operationId=op_id, sdk_op=sdk_op, config=specific_config
        )

    def _build_resolvers(self) -> dict[str, ModuleResolver]:
        """Builds a dictionary of ModuleResolver objects from the 'resolvers' config."""
        resolvers = {}
        resolver_configs = self.config.get("resolvers", {})

        for name, resolver_conf in resolver_configs.items():
            resolver_context_str = f"{self.context_str}, resolver '{name}'"
            list_op_id = resolver_conf.get("list")
            retrieve_op_id = resolver_conf.get("retrieve")

            if not list_op_id or not retrieve_op_id:
                self.collector.add_error(
                    f"{resolver_context_str}: Both 'list' and 'retrieve' operationIds are required."
                )
                continue

            list_op = self.api_parser.get_operation(list_op_id)
            retrieve_op = self.api_parser.get_operation(retrieve_op_id)

            if not list_op or not retrieve_op:
                self.collector.add_error(
                    f"{resolver_context_str}: One of the operationIds ('{list_op_id}' or '{retrieve_op_id}') was not found in the API spec."
                )
                continue

            # Create the structured ModuleResolver object.
            resolvers[name] = ModuleResolver(
                list_op_id=list_op_id,
                retrieve_op_id=retrieve_op_id,
                list_op=list_op,
                retrieve_op=retrieve_op,
                error_message=resolver_conf.get(
                    "error_message", f"{name.capitalize()} '{{value}}' not found."
                ),
            )

        return resolvers
