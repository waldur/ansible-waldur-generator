import re
from typing import Dict, Any, Optional

from ansible_waldur_generator.helpers import (
    OPENAPI_TO_ANSIBLE_TYPE_MAP,
    capitalize_first,
)

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

    def _generate_sample(
        self, prop_name: str, prop_schema: Dict[str, Any], resource_type: str | None
    ) -> Any:
        """
        Generates a sample value by applying rules in order of specificity.

        Args:
            prop_name: The name of the property (e.g., 'customer_name').
            prop_schema: The OpenAPI schema for the property.

        Returns:
            A sample value.
        """
        # Rule 1: Explicit 'example' from the schema has the highest priority.
        if "example" in prop_schema:
            return prop_schema["example"]

        # Rule 2: Use the first value from an 'enum' if available.
        if "enum" in prop_schema and prop_schema["enum"]:
            return prop_schema["enum"][0]

        # Rule 3: Sensitive data should be masked.
        if any(
            keyword in prop_name
            for keyword in ["password", "token", "secret", "api_key"]
        ):
            return "********"

        prop_type = prop_schema.get("type")

        # Rule 4: Name-based heuristics (most specific rules first).
        # This section contains the domain-specific intelligence.

        # --- Identifiers & Names ---
        if prop_name in ("username", "user_name"):
            return "alice"
        if prop_name == "customer_name":
            return "Big Corp Inc."
        if prop_name == "project_name":
            return "Internal Research Project"
        if prop_name == "name":
            return (
                f"My Awesome {(resource_type or 'Resource').replace('_', ' ').title()}"
            )
        if "hostname" in prop_name:
            return "server-01.example.com"
        if prop_name == "key":  # Could be a dictionary key or a resource key
            return "special-key"
        if prop_name in ("backend_id", "external_id"):
            return "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

        # --- Networking ---
        if "ip_address" in prop_name or "floating_ip" in prop_name:
            return "8.8.8.8"
        if "cidr" in prop_name:
            return "192.168.1.0/24"
        if "mac_address" in prop_name:
            return "00:1B:44:11:3A:B7"
        if "gateway" in prop_name:
            return "192.168.1.1"
        if "port" in prop_name and prop_type == "integer":  # Application port
            return 8080

        # --- Compute & Storage ---
        if prop_name == "size":
            return 100
        if "ram" in prop_name or "memory" in prop_name:
            return 2048
        if prop_name in ("cores", "vcpu", "cpu_count"):
            return 2
        if "disk" in prop_name:
            return 20480  # Often in MB

        # --- Status & Configuration ---
        if prop_name in ("status", "state"):
            return "OK"
        if prop_name == "description":
            return "This is a sample description for the resource."
        if prop_name == "user_data":
            return "#cloud-config\npackages:\n  - nginx"
        if prop_name == "schedule" or "cron" in prop_name:
            return "0 0 * * *"

        # --- Contact & Personal Info ---
        if "email" in prop_name:
            return "alice@example.com"
        if "phone" in prop_name:
            return "+1-202-555-0104"

        # Rule 5: Format-based generation (more generic than name-based).
        prop_format = prop_schema.get("format")
        if prop_type == "string":
            if prop_format == "uuid" or prop_name.endswith("_uuid"):
                return "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
            if prop_name.endswith("_by"):
                return "https://api.example.com/api/users/a1b2c3d4-e5f6-7890-abcd-ef1234567890/"
            if prop_format == "uri":
                return f"https://api.example.com/api/{prop_name.replace('_', '-')}/a1b2c3d4-e5f6-7890-abcd-ef1234567890/"
            if prop_format == "date-time":
                return "2023-10-01T12:00:00Z"
            if prop_format == "date":
                return "2023-10-01"
            if prop_format == "ipv4":
                return "192.168.1.100"
            if prop_format == "ipv6":
                return "2001:db8::1"
            if prop_format == "email":  # Fallback if name-based did not catch it
                return "user@example.com"
            if prop_format == "decimal":
                return "12.34"

        # Rule 6: Type-based fallback (most generic).
        if prop_type == "integer":
            return 123
        if prop_type == "number":
            return 123.45
        if prop_type == "boolean":
            return True
        if prop_type == "string":
            return "string-value"  # Generic fallback for unknown strings
        if prop_type == "array":
            return []
        if prop_type == "object":
            return {}

        return None

    def _traverse_schema(
        self, schema: Dict[str, Any], resource_type: str | None = None
    ) -> Dict[str, Any]:
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
                "description",
            )

            display_name = name.replace("_", " ")
            # Convert common abbreviations to uppercase
            display_name = re.sub(
                r"\b(ssh|ip|id|url|cpu|ram|vpn|uuid|dns)\b",
                lambda m: m.group(1).upper(),
                display_name,
                flags=re.IGNORECASE,
            )

            if not description:
                if resolved_prop_schema.get("format") == "uri":
                    description = f"{capitalize_first(display_name)} URL"
                elif resolved_prop_schema.get("type") == "array":
                    description = f"A list of {display_name} items."
                else:
                    description = capitalize_first(display_name)

            field_data = {
                "description": capitalize_first(description),
                "type": ansible_type,
                "returned": "always",
                "sample": self._generate_sample(
                    name, resolved_prop_schema, resource_type
                ),
            }

            # If it's a nested object, recurse.
            if ansible_type == "dict" and "properties" in resolved_prop_schema:
                field_data["contains"] = self._traverse_schema(
                    resolved_prop_schema, resource_type
                )
            # If it's a list of objects, find the item schema and recurse.
            elif ansible_type == "list" and "items" in resolved_prop_schema:
                item_schema = self._resolve_schema(resolved_prop_schema["items"])
                if item_schema.get("type") == "object":
                    field_data["contains"] = self._traverse_schema(
                        item_schema, resource_type
                    )

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
