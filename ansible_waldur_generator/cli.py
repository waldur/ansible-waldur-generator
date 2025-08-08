#!/usr/bin/env python

import os
import click
from .generator import Generator

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
DEFAULT_INPUT_DIR = os.path.join(PROJECT_ROOT, "inputs")
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "outputs")
DEFAULT_TEMPLATE_DIR = os.path.join(CURRENT_DIR, "templates")


@click.command()
@click.option(
    "--config",
    default=os.path.join(DEFAULT_INPUT_DIR, "generator_config.yaml"),
    help="Path to the generator config file.",
)
@click.option(
    "--api-spec",
    default=os.path.join(DEFAULT_INPUT_DIR, "waldur_api.yaml"),
    help="Path to the OpenAPI spec file.",
)
@click.option(
    "--output-dir",
    default=DEFAULT_OUTPUT_DIR,
    help="Directory to save the generated module.",
)
@click.option(
    "--template-dir",
    default=DEFAULT_TEMPLATE_DIR,
    help="Directory containing Jinja2 templates.",
)
def main(config, api_spec, output_dir, template_dir):
    """
    An Ansible Module Generator CLI.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    generator = Generator.from_files(
        config_path=config, api_spec_path=api_spec, template_dir=template_dir
    )

    generator.generate(output_dir=output_dir)


if __name__ == "__main__":
    main()
