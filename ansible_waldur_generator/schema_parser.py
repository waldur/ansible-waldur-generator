from typing import Dict, Any, Optional

from ansible_waldur_generator.helpers import OPENAPI_TO_ANSIBLE_TYPE_MAP

from copy import deepcopy


class ReturnBlockGenerator:
    """
    Generates an Ansible RETURN block dictionary from an OpenAPI response schema,
    with support for complex constructs like '$ref' and 'allOf'.
    """

    def __init__(self, full_api_spec: Dict[str, Any]):
        self.full_api_spec = full_api_spec

    def _get_schema_by_ref(self, ref: str) -> Optional[Dict[str, Any]]:
        """Follows a JSON schema $ref to retrieve a deep copy of the schema definition."""
        try:
            parts = ref.lstrip("#/").split("/")
            schema = self.full_api_spec
            for part in parts:
                schema = schema[part]
            # Return a deep copy to prevent modification of the original spec
            return deepcopy(schema)
        except (KeyError, IndexError):
            return None

    def _resolve_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fully resolves a schema, handling '$ref' and 'allOf' constructs.
        Returns a flattened schema with all properties combined.
        """
        # If the schema is a direct reference, resolve it first.
        if "$ref" in schema:
            # Create a new dictionary to hold the resolved schema and any sibling keys.
            # For example, if we have { "$ref": "...", "description": "hi" },
            # we need to preserve "description".
            ref_schema = self._get_schema_by_ref(schema["$ref"]) or {}
            # The sibling keys in the original schema override keys from the resolved ref.
            ref_schema.update({k: v for k, v in schema.items() if k != "$ref"})
            schema = ref_schema

        # Handle 'allOf' for schema composition
        if "allOf" in schema:
            # Start with the properties from the current schema level, excluding 'allOf' itself.
            final_schema = {k: v for k, v in schema.items() if k != "allOf"}

            # Ensure there's a 'properties' key to merge into.
            if "properties" not in final_schema:
                final_schema["properties"] = {}

            # Iterate through each sub-schema in the 'allOf' list.
            for sub_schema in schema["allOf"]:
                # Recursively resolve the sub-schema to get its flattened properties.
                resolved_sub_schema = self._resolve_schema(sub_schema)

                # Merge the properties from the sub-schema into our final schema.
                final_schema["properties"].update(
                    resolved_sub_schema.get("properties", {})
                )

                # Also merge any other top-level keys from the resolved sub-schema,
                # like 'type', but don't let it overwrite existing keys.
                for key, value in resolved_sub_schema.items():
                    if key not in final_schema:
                        final_schema[key] = value

            return final_schema

        return schema

    def _generate_sample(self, prop_schema: Dict[str, Any]) -> Any:
        """Generates a sample value based on the property's schema."""
        # This function remains the same as before.
        prop_type = prop_schema.get("type")
        if "example" in prop_schema:
            return prop_schema["example"]
        if prop_type == "string":
            if prop_schema.get("format") == "uuid":
                return "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
            if prop_schema.get("format") == "uri":
                return "https://api.example.com/api/resource/..."
            if prop_schema.get("format") == "decimal":
                return "123.45"
            if prop_schema.get("format") == "date-time":
                return "2023-10-01T12:00:00Z"
            if prop_schema.get("format") == "date":
                return "2023-10-01"
            if prop_schema.get("format") == "email":
                return "alice@gmail.com"
            if "name" in prop_schema.get("description", "").lower():
                return "My Resource Name"
            return "string_value"
        if prop_type == "integer":
            return 123
        if prop_type == "number":
            return 123.45
        if prop_type == "boolean":
            return True
        return None

    def _traverse_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively traverses a schema and builds the 'contains' dictionary
        for the Ansible RETURN block.
        """
        result = {}
        # First, fully resolve the top-level schema to handle any 'allOf' at this level.
        resolved_schema = self._resolve_schema(schema)
        properties = resolved_schema.get("properties", {})

        for name, prop_schema in properties.items():
            # Resolve the individual property schema, as it could also be a ref or have 'allOf'.
            resolved_prop_schema = self._resolve_schema(prop_schema)

            # Skip properties that are marked as write-only in the spec.
            if resolved_prop_schema.get("writeOnly"):
                continue

            ansible_type = OPENAPI_TO_ANSIBLE_TYPE_MAP.get(
                resolved_prop_schema.get("type", "string"), "str"
            )
            description = resolved_prop_schema.get(
                "description", name.replace("_", " ")
            ).strip()

            field_data = {
                "description": description,
                "type": ansible_type,
                "returned": "always",
                "sample": self._generate_sample(resolved_prop_schema),
            }

            # If it's a nested object, recurse.
            if ansible_type == "dict" and "properties" in resolved_prop_schema:
                field_data["contains"] = self._traverse_schema(resolved_prop_schema)
            # If it's a list of objects, find the item schema and recurse.
            elif ansible_type == "list" and "items" in resolved_prop_schema:
                item_schema = self._resolve_schema(resolved_prop_schema["items"])
                if item_schema.get("type") == "object":
                    field_data["contains"] = self._traverse_schema(item_schema)

            result[name] = field_data
        return result

    def generate_for_operation(
        self, operation_spec: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Finds the success response schema for a given operation and generates
        the RETURN block for it.
        """
        for status_code in ["200", "201"]:
            response_spec = operation_spec.get("responses", {}).get(status_code)
            if not response_spec:
                continue

            schema_container = (
                response_spec.get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            if not schema_container:
                continue

            # The schema could be a direct reference or an array of references.
            schema_to_process = None
            if schema_container.get("type") == "array":
                schema_to_process = schema_container.get("items", {})
            else:
                schema_to_process = schema_container

            if schema_to_process:
                # The _traverse_schema method will handle the resolution internally.
                return self._traverse_schema(schema_to_process)

        return None
