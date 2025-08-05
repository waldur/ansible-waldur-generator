"""
This is the main orchestrator for the Ansible module generation process.

It coordinates the parsing of input files, the building of the template context,
and the final rendering of the output module files.
"""

import os
import sys
import yaml
from jinja2 import Environment, FileSystemLoader

from .parser import ApiSpecParser, ConfigParser
from .builder import ContextBuilder


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


class Generator:
    """Orchestrates the Ansible module generation process."""

    def __init__(self, config_data, api_spec_data, template_dir):
        """
        Initializes the generator with data dictionaries.

        Args:
            config_data (dict): The generator configuration data.
            api_spec_data (dict): The OpenAPI specification data.
            template_dir (str): Path to the directory with Jinja2 templates.
        """
        self.config_data = config_data
        self.api_spec_data = api_spec_data
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir), trim_blocks=True, lstrip_blocks=True
        )

    @classmethod
    def from_files(cls, config_path, api_spec_path, template_dir):
        """Creates a Generator instance by loading configuration and spec from files."""
        try:
            with open(config_path, "r") as f:
                config_data = yaml.safe_load(f)
        except (IOError, yaml.YAMLError) as e:
            print(
                f"Error reading or parsing config file '{config_path}': {e}",
                file=sys.stderr,
            )
            sys.exit(1)

        try:
            with open(api_spec_path, "r") as f:
                api_spec_data = yaml.safe_load(f)
        except (IOError, yaml.YAMLError) as e:
            print(
                f"Error reading or parsing API spec file '{api_spec_path}': {e}",
                file=sys.stderr,
            )
            sys.exit(1)

        return cls(config_data, api_spec_data, template_dir)

    def generate(self, output_dir: str):
        """
        Runs the full generation process for all modules defined in the configuration.
        """
        # A single collector for the initial parsing phase.
        initial_collector = ValidationErrorCollector()

        # 1. Parse API spec once to get a map of all available SDK operations.
        api_parser = ApiSpecParser(self.api_spec_data, initial_collector)
        op_map = api_parser.parse()

        # 2. Parse the main generator config to get a list of structured module configurations.
        # This step also performs normalization and initial validation.
        config_parser = ConfigParser(self.config_data, op_map, initial_collector)
        module_configs = config_parser.parse()

        # If there were fundamental errors during parsing (e.g., missing tags, bad refs),
        # report them and stop before trying to build contexts.
        initial_collector.report()

        # 3. For each valid module configuration, build the full context and render the template.
        for module_config in module_configs:
            # Use a fresh collector for each module's context-building phase
            # to provide isolated and clear error messages.
            module_collector = ValidationErrorCollector()

            try:
                # 3a. Instantiate the builder with the validated config and the full API spec.
                builder = ContextBuilder(
                    module_config, self.api_spec_data, module_collector
                )

                # 3b. Build the final context, performing deeper validations (e.g., for resolvers).
                context = builder.build()

                # If the builder found errors (like missing resolvers for URI fields), report and skip.
                if module_collector.has_errors:
                    print(
                        f"\nSkipping module '{module_config.module_key}' due to errors found during context building:",
                        file=sys.stderr,
                    )
                    module_collector.report()  # This will print errors and exit.
                    continue  # This line is technically not reached, but good for clarity.

                # 3c. Render the Jinja2 template with the final context.
                # The context is a dataclass; we render it as a dictionary.
                context_dict = context.to_dict()
                rendered_template = self.jinja_env.get_template(
                    "resource_module.py.j2"
                ).render(context_dict)

                # 3d. Write the rendered content to the output file.
                output_path = os.path.join(output_dir, f"{context.module_name}.py")
                with open(output_path, "w") as f:
                    f.write(rendered_template)
                print(f"Successfully generated module: {output_path}")

            except Exception as e:
                # Catch any unexpected errors during a single module's processing
                # and report them without stopping the entire generation process.
                print(
                    f"\nAn unexpected error occurred while processing module '{module_config.module_key}': {e}",
                    file=sys.stderr,
                )
