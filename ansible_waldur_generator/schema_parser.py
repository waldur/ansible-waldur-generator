import re
from typing import Dict, Any, Optional
from copy import deepcopy

from ansible_waldur_generator.helpers import (
    OPENAPI_TO_ANSIBLE_TYPE_MAP,
    capitalize_first,
)


class ReturnBlockGenerator:
    """
    A comprehensive schema processor for generating Ansible documentation blocks
    (RETURN and EXAMPLES) from an OpenAPI specification. It is designed to handle
    complex schema constructs such as '$ref' for references and 'allOf' for
    composition, and it uses a set of heuristics to generate realistic sample data.
    """

    def __init__(self, full_api_spec: Dict[str, Any]):
        """
        Initializes the processor with the complete OpenAPI specification.

        Args:
            full_api_spec: The parsed dictionary of the entire waldur_api.yaml file.
        """
        self.full_api_spec = full_api_spec

    def _get_schema_by_ref(self, ref: str) -> Optional[Dict[str, Any]]:
        """
        Follows a JSON schema '$ref' path (e.g., '#/components/schemas/Project')
        to retrieve a deep copy of the referenced schema definition from the spec.
        """
        try:
            parts = ref.lstrip("#/").split("/")
            schema = self.full_api_spec
            for part in parts:
                schema = schema[part]
            # Return a deep copy to prevent any modifications to the original spec
            # during processing.
            return deepcopy(schema)
        except (KeyError, IndexError):
            # The reference path was invalid.
            return None

    def _resolve_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fully resolves a given schema fragment by handling '$ref' and 'allOf' constructs.
        It returns a single, flattened schema with all properties combined, making it
        easier for other methods to process.
        """
        # Step 1: Handle '$ref' at the top level. If the schema is a reference,
        # replace it with the referenced content. Sibling keys (like a 'description'
        # next to a '$ref') are preserved and will override the referenced content.
        if "$ref" in schema:
            ref_schema = self._get_schema_by_ref(schema["$ref"]) or {}
            ref_schema.update({k: v for k, v in schema.items() if k != "$ref"})
            schema = ref_schema

        # Step 2: Handle 'allOf' for schema composition. This is used when a model
        # inherits properties from multiple other models.
        if "allOf" in schema:
            # Start with the properties from the current schema level.
            final_schema = {k: v for k, v in schema.items() if k != "allOf"}
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

            return final_schema

        return schema

    def _generate_sample_value(
        self, prop_name: str, prop_schema: Dict[str, Any], resource_type: str | None
    ) -> Any:
        """
        Generates a realistic sample value for a single property using a
        prioritized set of rules and heuristics. This is the "intelligence"
        behind creating useful examples.
        """
        # Rule 1: Highest priority. An explicit 'example' in the schema is always used.
        if "example" in prop_schema:
            return prop_schema["example"]

        # Rule 2: If the schema defines a list of choices, pick the first one.
        if "enum" in prop_schema and prop_schema["enum"]:
            return prop_schema["enum"][0]

        # Rule 3: Mask sensitive data based on common keywords in the property name.
        if any(
            keyword in prop_name
            for keyword in ["password", "token", "secret", "api_key"]
        ):
            return "********"

        prop_type = prop_schema.get("type")

        if prop_type == "array":
            if "security_groups" in prop_name:
                return ["web-server-sg"]
            if "floating_ips" in prop_name:
                return ["8.8.8.8"]
            if "ports" in prop_name:
                return ["private-vlan-port"]
            return []  # Default for unknown arrays

        # Rule 4: Name-based heuristics (most specific rules first).
        # This section contains the domain-specific intelligence for generating
        # contextually relevant and realistic data.

        # --- Identifiers & Names ---
        if prop_name in ("username", "user_name"):
            return "alice"
        if prop_name == "customer_name":
            return "Big Corp Inc."
        if prop_name == "project_name":
            return "Internal Research Project"
        if prop_name == "name":
            # Generate a descriptive name based on the resource type.
            return f"My-Awesome-{(resource_type or 'Resource').replace(' ', '-')}"
        if "hostname" in prop_name:
            return "server-01.example.com"
        if prop_name == "key":
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
        if "port" in prop_name and prop_type == "integer":
            return 8080  # Default to a common application port.

        # --- Compute & Storage ---
        if prop_name == "size":
            return 100
        if "ram" in prop_name or "memory" in prop_name:
            return 2048
        if prop_name in ("cores", "vcpu", "cpu_count"):
            return 2
        if "disk" in prop_name:
            return 20480

        # --- Status & Configuration ---
        if prop_name in ("status", "state"):
            return "OK"
        if prop_name == "description":
            return "A sample description created by Ansible."
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
        # This catches common data types not covered by specific name heuristics.
        prop_format = prop_schema.get("format")
        if prop_type == "string":
            if prop_format == "uuid" or prop_name.endswith("_uuid"):
                return "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
            if prop_name.endswith(
                "_by"
            ):  # Heuristic for 'created_by', 'modified_by' fields
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
            if prop_format == "email":
                return "user@example.com"
            if prop_format == "decimal":
                return "12.34"

        # Rule 6: Type-based fallback (most generic).
        # This is the last resort before returning nothing.
        if prop_type == "integer":
            return 123
        if prop_type == "number":
            return 123.45
        if prop_type == "boolean":
            return True
        if prop_type == "string":
            return "string-value"
        if prop_type == "array":
            return []
        if prop_type == "object":
            return {}

        # Final fallback if no rules match.
        return None

    def generate_example_from_schema(
        self, schema: Dict[str, Any], resource_type: str
    ) -> Dict[str, Any]:
        """
        Recursively traverses a schema and builds a complete example dictionary
        suitable for the Ansible EXAMPLES block. It only includes properties that
        a user would provide (i.e., it skips 'readOnly' fields).
        """
        example_data = {}
        # First, fully resolve the schema to handle any top-level 'allOf' or '$ref'.
        resolved_schema = self._resolve_schema(schema)
        properties = resolved_schema.get("properties", {})

        for name, prop_schema in properties.items():
            # Resolve the individual property's schema as well.
            resolved_prop_schema = self._resolve_schema(prop_schema)

            # Skip read-only fields as they are not user-provided input.
            if resolved_prop_schema.get("readOnly"):
                continue

            prop_type = resolved_prop_schema.get("type")

            # For nested objects, make a recursive call.
            if prop_type == "object" and "properties" in resolved_prop_schema:
                example_data[name] = self.generate_example_from_schema(
                    resolved_prop_schema, resource_type
                )
            # For arrays of objects, generate one example item and wrap it in a list.
            elif prop_type == "array" and "items" in resolved_prop_schema:
                # First, fully resolve the schema of the items within the array.
                item_schema = self._resolve_schema(resolved_prop_schema["items"])
                # Check if the items are themselves complex objects.
                if item_schema.get("type") == "object":
                    # If they are objects, we must recurse to generate a populated object.
                    # We wrap the result in a list to represent the array.
                    example_data[name] = [
                        self.generate_example_from_schema(item_schema, resource_type)
                    ]
                else:
                    # If the items are simple types (string, int, etc.), we generate
                    # a list containing one sample value.
                    example_data[name] = [
                        self._generate_sample_value(name, item_schema, resource_type)
                    ]
            # For primitive types (string, int, etc.), generate a single sample value.
            else:
                example_data[name] = self._generate_sample_value(
                    name, resolved_prop_schema, resource_type
                )

        return example_data

    def _traverse_schema(
        self, schema: Dict[str, Any], resource_type: str | None = None
    ) -> Dict[str, Any]:
        """
        Recursively traverses a schema to build the 'contains' dictionary for the
        Ansible RETURN block. This method processes all fields, including 'readOnly' ones,
        as it describes the data *returned* by the API.
        """
        result = {}
        resolved_schema = self._resolve_schema(schema)
        properties = resolved_schema.get("properties", {})

        for name, prop_schema in properties.items():
            resolved_prop_schema = self._resolve_schema(prop_schema)

            # Skip properties marked as write-only in the spec (e.g., passwords).
            if resolved_prop_schema.get("writeOnly"):
                continue

            ansible_type = OPENAPI_TO_ANSIBLE_TYPE_MAP.get(
                resolved_prop_schema.get("type", "string"), "str"
            )

            description = self.generate_description(resolved_prop_schema, name)

            field_data = {
                "description": description,
                "type": ansible_type,
                "returned": "always",
                # Use our smart sample generator for consistency in documentation.
                "sample": self._generate_sample_value(
                    name, resolved_prop_schema, resource_type
                ),
            }

            # If it's a nested dictionary, recurse to document its contents.
            if ansible_type == "dict" and "properties" in resolved_prop_schema:
                field_data["contains"] = self._traverse_schema(
                    resolved_prop_schema, resource_type
                )
            # If it's a list of dictionaries, find the item schema and recurse.
            elif ansible_type == "list" and "items" in resolved_prop_schema:
                item_schema = self._resolve_schema(resolved_prop_schema["items"])
                if item_schema.get("type") == "object":
                    field_data["contains"] = self._traverse_schema(
                        item_schema, resource_type
                    )

            result[name] = field_data
        return result

    def generate_description(
        self, resolved_prop_schema: Dict[str, Any], name: str
    ) -> str:
        description = resolved_prop_schema.get("description")

        # Create a more readable display name from the property name.
        display_name = name.replace("_", " ")
        # Convert common abbreviations to uppercase for better readability (e.g., ip -> IP).
        display_name = re.sub(
            r"\b(ssh|ip|id|url|cpu|ram|vpn|uuid|dns|cidr)\b",
            lambda m: m.group(1).upper(),
            display_name,
            flags=re.IGNORECASE,
        )

        # If no description is provided in the schema, generate a sensible default.
        if not description:
            if resolved_prop_schema.get("format") == "uri":
                description = f"{capitalize_first(display_name)} URL"
            elif resolved_prop_schema.get("type") == "array":
                description = f"A list of {display_name} items."
            else:
                description = capitalize_first(display_name)

        return description

    def generate_for_operation(
        self, operation_spec: Dict[str, Any], resource_type: str | None = None
    ) -> Optional[Dict[str, Any]]:
        """
        Finds the success response schema (200 or 201) for a given API operation
        and generates the full RETURN block structure for it.
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

            # The top-level response could be a single object or an array of objects.
            schema_to_process = None
            if schema_container.get("type") == "array":
                # For a list response, we document the structure of a single item.
                schema_to_process = schema_container.get("items", {})
            else:
                schema_to_process = schema_container

            if schema_to_process:
                # The _traverse_schema method will handle the resolution internally.
                return self._traverse_schema(schema_to_process, resource_type)

        return None
