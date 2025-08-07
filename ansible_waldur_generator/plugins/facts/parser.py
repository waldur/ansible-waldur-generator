from ansible_waldur_generator.interfaces.parser import BaseConfigParser
from ansible_waldur_generator.plugins.crud.config import ModuleIdempotencySection
from ansible_waldur_generator.plugins.facts.config import FactsModuleConfig


class FactsConfigParser(BaseConfigParser):
    """Parses and validates configuration for a 'facts' module."""

    def parse(self) -> FactsModuleConfig | None:
        """Builds and validates a FactsModuleConfig object based on conventions."""
        config = self.raw_config
        context_str = f"Module '{self.module_key}'"

        list_op_id = config.get("list_operation")
        if not list_op_id:
            self.collector.add_error(f"{context_str}: Missing 'list_operation' key.")
            return None

        list_sdk_op = self.api_parser.get_operation(list_op_id)
        if not list_sdk_op:
            self.collector.add_error(
                f"The specified operationId '{list_op_id}' could not be resolved from the API spec."
            )
            return None

        retrieve_op_id = config.get("retrieve_operation")
        if not retrieve_op_id:
            self.collector.add_error(
                f"{context_str}: Missing 'retrieve_operation' key."
            )
            return None

        retrieve_sdk_op = self.api_parser.get_operation(retrieve_op_id)
        if not retrieve_sdk_op:
            self.collector.add_error(
                f"The specified operationId '{retrieve_op_id}' could not be resolved from the API spec."
            )
            return None

        resource_type = config.get("resource_type")
        if not resource_type:
            self.collector.add_error(f"{context_str}: Missing 'resource_type' key.")
            return None

        list_section = ModuleIdempotencySection(
            operationId=list_op_id,
            sdk_op=list_sdk_op,
        )

        retrieve_section = ModuleIdempotencySection(
            operationId=retrieve_op_id,
            sdk_op=retrieve_sdk_op,
        )

        if not list_section or not retrieve_section:
            return None

        context_params = [
            {
                "name": "project",
                "type": "str",
                "required": True,
                "description": "The name or UUID of the project.",
                "resolver": {
                    "list": "projects_list",
                    "retrieve": "projects_retrieve",
                    "filter_key": "project_uuid",
                },
            }
        ]

        return FactsModuleConfig(
            module_key=self.module_key,
            description=config.get(
                "description", f"Get an existing {resource_type.replace('_', ' ')}."
            ),
            resource_type=resource_type,
            list_op=list_section,
            retrieve_op=retrieve_section,
            identifier_param="name",
            context_params=context_params,
        )
