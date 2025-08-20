from typing import Dict, Any, Optional

from .models import ApiOperation
from .helpers import ValidationErrorCollector


class ApiSpecParser:
    """
    Parses an OpenAPI specification to extract information about API operations.
    """

    def __init__(
        self, api_spec_data: Dict[str, Any], collector: ValidationErrorCollector
    ):
        """
        Initializes the parser with the OpenAPI specification data.

        Args:
            api_spec_data: The parsed OpenAPI specification.
            collector: An instance of ValidationErrorCollector to log errors.
        """
        self.api_spec = api_spec_data
        self.collector = collector

    def get_operation(self, operation_id: str) -> Optional[ApiOperation]:
        """
        Retrieves a single API operation by its operationId.

        Args:
            operation_id: The unique identifier for the operation.

        Returns:
            An ApiOperation object if the operation is found, otherwise None.
        """
        for path, methods in self.api_spec.get("paths", {}).items():
            for method, operation in methods.items():
                if operation.get("operationId") != operation_id:
                    continue

                model_schema = None
                request_body_schema = (
                    operation.get("requestBody", {})
                    .get("content", {})
                    .get("application/json", {})
                    .get("schema", {})
                )
                if request_body_schema:
                    schema_ref = request_body_schema.get("$ref")
                    if schema_ref:
                        try:
                            model_schema = self.get_schema_by_ref(schema_ref)
                        except ValueError as e:
                            self.collector.add_error(
                                f"For operation '{operation_id}': {e}"
                            )
                            return None
                    else:
                        model_schema = request_body_schema

                return ApiOperation(
                    path=path,
                    method=method.upper(),
                    operation_id=operation_id,
                    model_schema=model_schema,
                    raw_spec=operation,
                )
        return None

    def get_schema_by_ref(self, ref: str) -> Dict[str, Any]:
        """
        Resolves a JSON schema $ref to its definition within the API specification.

        Args:
            ref: The JSON schema reference (e.g., '#/components/schemas/MyModel').

        Returns:
            The resolved schema as a dictionary.

        Raises:
            ValueError: If the reference is invalid or cannot be resolved.
        """
        parts = ref.lstrip("#/").split("/")
        schema = self.api_spec
        for part in parts:
            schema = schema.get(part)
            if schema is None:
                raise ValueError(
                    f"Invalid $ref, part '{part}' not found in spec: {ref}"
                )
        return schema
