import importlib
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

    def get_operation(self, operation_id: str) -> Optional[SdkOperation]:
        """
        Get a single operation from the API spec by its operationId.

        Args:
            operation_id: The operationId to look for.

        Returns:
            SdkOperation object if found, None otherwise.
        """
        for methods in self.api_spec.get("paths", {}).values():
            for operation in methods.values():
                op_id = operation.get("operationId")
                if op_id != operation_id:
                    continue

                tags = operation.get("tags")
                if not tags:
                    self.collector.add_error(f"Operation '{op_id}' is missing 'tags'.")
                    return None

                return self._build_sdk_operation(op_id, tags, operation)
        return None

    def _build_sdk_operation(
        self, op_id: str, tags: List[str], operation: Dict[str, Any]
    ) -> Optional[SdkOperation]:
        """Extracts all relevant information for a single operation."""
        # Convention: the first tag determines the resource and thus the SDK module.
        resource_name = tags[0].replace("-", "_")

        sdk_module_name = f"{self.sdk_base_path}.api.{resource_name}"
        sdk_function_name = op_id

        model_class_name, model_module_name, model_schema, model_class = (
            None,
            None,
            None,
            None,
        )

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
            model_class_name = model_name
            model_module_name = (
                f"{self.sdk_base_path}.models.{to_snake_case(model_name)}"
            )
            try:
                model_schema = self.get_schema_by_ref(schema_ref)
                model_module = importlib.import_module(model_module_name)
                model_class = getattr(model_module, model_class_name)
            except (ValueError, ImportError, AttributeError) as e:
                self.collector.add_error(
                    f"For operation '{op_id}': Could not import model class '{model_class_name}' from '{model_module_name}': {e}"
                )
                return None

        try:
            # The function itself is now the primary object we import.
            # Assuming SDK functions are directly in the module.
            sdk_function_module = importlib.import_module(
                f"{sdk_module_name}.{sdk_function_name}"
            )
        except (ImportError, AttributeError) as e:
            self.collector.add_error(
                f"For operation '{op_id}': Could not import SDK function '{sdk_function_name}' from '{sdk_module_name}': {e}"
            )
            return None

        return SdkOperation(
            sdk_module_name=sdk_module_name,
            sdk_function_name=sdk_function_name,
            sdk_function=sdk_function_module,
            model_class_name=model_class_name,
            model_class=model_class,
            model_module_name=model_module_name,
            model_schema=model_schema,
            raw_spec=operation,
        )

    def get_schema_by_ref(self, ref: str) -> Dict[str, Any]:
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
