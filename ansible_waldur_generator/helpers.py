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
        "no_log": True,  # Sensitive information, do not log
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


def capitalize_first(s: str) -> str:
    """Capitalizes the first letter of a string without lowercasing the rest."""
    if not s:
        return ""
    return s[0].upper() + s[1:]


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
