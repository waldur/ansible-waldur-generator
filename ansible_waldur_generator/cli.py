#!/usr/bin/env python

import os
import argparse
from .generator import Generator

# Define default paths relative to the current file's location
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
DEFAULT_INPUT_DIR = os.path.join(PROJECT_ROOT, "inputs")
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "outputs")


def main():
    """
    Main function to parse command-line arguments and run the Ansible Module Generator.
    """
    # 1. Initialize the ArgumentParser
    parser = argparse.ArgumentParser(
        prog="generate",
        description="An Ansible Module Generator for the Waldur API.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,  # Shows default values in help
    )

    # 2. Define the command-line arguments
    parser.add_argument(
        "--config",
        default=os.path.join(DEFAULT_INPUT_DIR, "generator_config.yaml"),
        help="Path to the generator config file.",
    )
    parser.add_argument(
        "--api-spec",
        default=os.path.join(DEFAULT_INPUT_DIR, "waldur_api.yaml"),
        help="Path to the OpenAPI spec file.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to save the generated Ansible collection.",
    )

    # 3. Parse the arguments from the command line
    args = parser.parse_args()

    # 4. The rest of the logic remains the same
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)

    # Instantiate the generator using the parsed arguments
    generator = Generator.from_files(
        config_path=args.config, api_spec_path=args.api_spec
    )

    # Run the generation process
    generator.generate(output_dir=args.output_dir)
    print("\nGeneration complete.")


if __name__ == "__main__":
    main()
