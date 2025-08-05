"""Shared helper functions and constants."""

import re
import sys

# Mapping from OpenAPI types to Ansible module types.
OPENAPI_TO_ANSIBLE_TYPE_MAP = {
    "string": "str",
    "number": "float",
    "integer": "int",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}

AUTH_OPTIONS = {
    "access_token": {
        "description": "An access token.",
        "required": True,
        "type": "str",
    },
    "api_url": {
        "description": "Fully qualified URL to the API.",
        "required": True,
        "type": "str",
    },
}


def to_snake_case(name):
    """Converts CamelCase to snake_case."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


class ValidationErrorCollector:
    """A simple class to collect and report validation errors."""

    def __init__(self):
        self.errors = []

    def add_error(self, message: str):
        self.errors.append(message)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def report(self):
        """Prints all collected errors to stderr and exits if any exist."""
        if self.has_errors:
            print(
                "\nGeneration failed with the following configuration errors:",
                file=sys.stderr,
            )
            for i, error in enumerate(self.errors, 1):
                print(f"  {i}. {error}", file=sys.stderr)
            sys.exit(1)


class CodeLiteral:
    """A wrapper to mark a string that should be rendered as raw Python code."""

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return str(self.value)


def to_python_code_string(data, indent_level=0):
    """
    Recursively serializes a Python data structure into a pretty-printed
    string of Python code. It respects the CodeLiteral marker.
    """
    indent = " " * indent_level

    if isinstance(data, CodeLiteral):
        # If it's a CodeLiteral, render its value directly without quotes.
        return data.value

    if isinstance(data, str):
        # Standard strings are safely quoted.
        return repr(data)

    if isinstance(data, (int, float, bool, type(None))):
        # These types have a perfect string representation already.
        return str(data)

    if isinstance(data, list):
        # Recursively serialize list items.
        items = [to_python_code_string(item, indent_level + 4) for item in data]
        return "[\n" + ",\n".join(items) + f",\n{indent}]"

    if isinstance(data, dict):
        # Recursively serialize dictionary items.
        lines = ["{"]
        for key, value in data.items():
            # Keys are always strings, so we repr() them.
            key_repr = repr(key)
            # Values are processed by our generic function.
            value_repr = to_python_code_string(value, indent_level + 4)
            lines.append(f"{' ' * (indent_level + 4)}{key_repr}: {value_repr},")
        lines.append(f"{indent}}}")
        return "\n".join(lines)

    # Fallback for any other type
    return str(data)
