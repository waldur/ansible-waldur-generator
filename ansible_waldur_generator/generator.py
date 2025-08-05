"""
This is the main orchestrator for the Ansible module generation process.

It coordinates the parsing of input files, the building of the template context,
and the final rendering of the output module files.
"""

import os
import sys
import yaml
from jinja2 import Environment, FileSystemLoader

from ansible_waldur_generator.helpers import ValidationErrorCollector
from ansible_waldur_generator.plugin_manager import PluginManager

from .api_parser import ApiSpecParser


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
        self.plugin_manager = PluginManager()

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
        collector = ValidationErrorCollector()

        # 1. Parse API spec once to get a map of all available SDK operations.
        api_parser = ApiSpecParser(self.api_spec_data, collector)
        collector.report()  # Fail fast on API spec errors

        # 2. Iterate through modules and delegate to the appropriate plugin.
        for module_key, raw_config in self.config_data.get("modules", {}).items():
            module_type = raw_config.get("type")

            # 2a. Ask the Plugin Manager for the correct plugin.
            plugin = self.plugin_manager.get_plugin(module_type)
            if not plugin:
                collector.add_error(
                    f"Module '{module_key}': No plugin found for type '{module_type}'."
                )
                continue

            try:
                # 2b. Get the specific parser from the plugin and run it.
                parser = plugin.get_parser(
                    module_key, raw_config, api_parser, collector
                )
                module_config = parser.parse()

                if collector.has_errors or not module_config:
                    # Errors for this module will be reported at the end
                    continue

                # 2c. Get the specific builder from the plugin and run it.
                builder = plugin.get_builder(module_config, api_parser, collector)
                context = builder.build()

                if collector.has_errors:
                    continue

                # 2d. Get the template name from the plugin and render.
                template_name = plugin.get_template_name()
                rendered_template = self.jinja_env.get_template(template_name).render(
                    context.to_dict()
                )

                output_path = os.path.join(output_dir, f"{context.module_name}.py")
                with open(output_path, "w") as f:
                    f.write(rendered_template)
                print(f"Successfully generated module: {output_path}")

            except Exception as e:
                collector.add_error(
                    f"Unexpected error in plugin for '{module_type}' on module '{module_key}': {e}"
                )

        collector.report()  # Report any final errors
