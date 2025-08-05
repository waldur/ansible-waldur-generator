from typing import Dict, List, Any, Optional

from .models import SdkOperation
from .helpers import ValidationErrorCollector, to_snake_case


class ApiSpecParser:
    """Parses an OpenAPI specification into a map of SdkOperation objects."""

    def __init__(
        self, api_spec_data: Dict[str, Any], collector: ValidationErrorCollector
    ):
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
