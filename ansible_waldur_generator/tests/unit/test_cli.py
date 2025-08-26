"""Tests for the CLI module."""

import os
import tempfile
import shutil
from unittest.mock import Mock, patch
import pytest
import yaml

from ansible_waldur_generator import cli


class TestCliConstants:
    """Test CLI constants and path resolution."""

    def test_current_dir_resolution(self):
        """Test that CURRENT_DIR points to the CLI module directory."""
        expected = os.path.dirname(os.path.abspath(cli.__file__))
        assert cli.CURRENT_DIR == expected

    def test_project_root_resolution(self):
        """Test that PROJECT_ROOT is correctly resolved."""
        expected = os.path.dirname(cli.CURRENT_DIR)
        assert cli.PROJECT_ROOT == expected

    def test_default_input_dir(self):
        """Test default input directory path."""
        expected = os.path.join(cli.PROJECT_ROOT, "inputs")
        assert cli.DEFAULT_INPUT_DIR == expected

    def test_default_output_dir(self):
        """Test default output directory path."""
        expected = os.path.join(cli.PROJECT_ROOT, "outputs")
        assert cli.DEFAULT_OUTPUT_DIR == expected


class TestCliArgumentParsing:
    """Test CLI argument parsing functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.temp_dir, "config.yaml")
        self.api_spec_file = os.path.join(self.temp_dir, "api_spec.yaml")
        self.output_dir = os.path.join(self.temp_dir, "output")

        # Create test files
        test_config = {"collections": []}
        test_api_spec = {"openapi": "3.0.0", "paths": {}}

        with open(self.config_file, "w") as f:
            yaml.dump(test_config, f)

        with open(self.api_spec_file, "w") as f:
            yaml.dump(test_api_spec, f)

    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("ansible_waldur_generator.cli.Generator")
    @patch("sys.argv", ["generate"])
    def test_main_with_default_arguments(self, mock_generator_class):
        """Test main function with default arguments."""
        mock_generator = Mock()
        mock_generator_class.from_files.return_value = mock_generator

        with patch("os.path.exists", return_value=True):
            cli.main()

        # Verify Generator.from_files was called with default paths
        expected_config = os.path.join(cli.DEFAULT_INPUT_DIR, "generator_config.yaml")
        expected_api_spec = os.path.join(cli.DEFAULT_INPUT_DIR, "waldur_api.yaml")

        mock_generator_class.from_files.assert_called_once_with(
            config_path=expected_config, api_spec_path=expected_api_spec
        )

        # Verify generate was called with default output dir
        mock_generator.generate.assert_called_once_with(
            output_dir=cli.DEFAULT_OUTPUT_DIR
        )

    @patch("ansible_waldur_generator.cli.Generator")
    @patch(
        "sys.argv",
        [
            "generate",
            "--config",
            "/custom/config.yaml",
            "--api-spec",
            "/custom/api.yaml",
            "--output-dir",
            "/custom/output",
        ],
    )
    def test_main_with_custom_arguments(self, mock_generator_class):
        """Test main function with custom arguments."""
        mock_generator = Mock()
        mock_generator_class.from_files.return_value = mock_generator

        with patch("os.path.exists", return_value=True):
            cli.main()

        # Verify Generator.from_files was called with custom paths
        mock_generator_class.from_files.assert_called_once_with(
            config_path="/custom/config.yaml", api_spec_path="/custom/api.yaml"
        )

        # Verify generate was called with custom output dir
        mock_generator.generate.assert_called_once_with(output_dir="/custom/output")

    @patch("ansible_waldur_generator.cli.Generator")
    @patch("os.makedirs")
    @patch("os.path.exists", return_value=False)
    @patch("sys.argv", ["generate"])
    def test_main_creates_output_directory_if_missing(
        self, mock_exists, mock_makedirs, mock_generator_class
    ):
        """Test that main creates output directory if it doesn't exist."""
        mock_generator = Mock()
        mock_generator_class.from_files.return_value = mock_generator

        cli.main()

        # Verify makedirs was called for the default output directory
        mock_makedirs.assert_called_once_with(cli.DEFAULT_OUTPUT_DIR)

    @patch("ansible_waldur_generator.cli.Generator")
    @patch("os.makedirs")
    @patch("os.path.exists", return_value=True)
    @patch("sys.argv", ["generate"])
    def test_main_skips_creating_existing_output_directory(
        self, mock_exists, mock_makedirs, mock_generator_class
    ):
        """Test that main doesn't create output directory if it exists."""
        mock_generator = Mock()
        mock_generator_class.from_files.return_value = mock_generator

        cli.main()

        # Verify makedirs was not called
        mock_makedirs.assert_not_called()

    @patch("ansible_waldur_generator.cli.Generator")
    @patch("builtins.print")
    @patch("os.path.exists", return_value=True)
    @patch("sys.argv", ["generate"])
    def test_main_prints_completion_message(
        self, mock_exists, mock_print, mock_generator_class
    ):
        """Test that main prints completion message."""
        mock_generator = Mock()
        mock_generator_class.from_files.return_value = mock_generator

        cli.main()

        # Verify completion message was printed
        mock_print.assert_called_with("\nGeneration complete.")


class TestCliIntegration:
    """Test CLI integration with real argument parsing."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.temp_dir, "config.yaml")
        self.api_spec_file = os.path.join(self.temp_dir, "api_spec.yaml")
        self.output_dir = os.path.join(self.temp_dir, "output")

        # Create test files
        test_config = {"collections": []}
        test_api_spec = {"openapi": "3.0.0", "paths": {}}

        with open(self.config_file, "w") as f:
            yaml.dump(test_config, f)

        with open(self.api_spec_file, "w") as f:
            yaml.dump(test_api_spec, f)

    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("ansible_waldur_generator.cli.Generator")
    def test_real_argument_parsing_integration(self, mock_generator_class):
        """Test real argument parsing with actual argparse."""
        mock_generator = Mock()
        mock_generator_class.from_files.return_value = mock_generator

        # Test with real argument parsing
        with patch(
            "sys.argv",
            [
                "generate",
                "--config",
                self.config_file,
                "--api-spec",
                self.api_spec_file,
                "--output-dir",
                self.output_dir,
            ],
        ):
            with patch("os.path.exists", return_value=False):
                with patch("os.makedirs"):
                    cli.main()

        # Verify the correct arguments were passed
        mock_generator_class.from_files.assert_called_once_with(
            config_path=self.config_file, api_spec_path=self.api_spec_file
        )
        mock_generator.generate.assert_called_once_with(output_dir=self.output_dir)


class TestCliErrorHandling:
    """Test CLI error handling scenarios."""

    @patch("ansible_waldur_generator.cli.Generator")
    @patch("sys.argv", ["generate"])
    def test_generator_from_files_error_propagates(self, mock_generator_class):
        """Test that Generator.from_files errors are propagated."""
        mock_generator_class.from_files.side_effect = FileNotFoundError(
            "Config file not found"
        )

        with patch("os.path.exists", return_value=True):
            with pytest.raises(FileNotFoundError, match="Config file not found"):
                cli.main()

    @patch("ansible_waldur_generator.cli.Generator")
    @patch("sys.argv", ["generate"])
    def test_generator_generate_error_propagates(self, mock_generator_class):
        """Test that Generator.generate errors are propagated."""
        mock_generator = Mock()
        mock_generator.generate.side_effect = ValueError("Invalid configuration")
        mock_generator_class.from_files.return_value = mock_generator

        with patch("os.path.exists", return_value=True):
            with pytest.raises(ValueError, match="Invalid configuration"):
                cli.main()

    @patch("ansible_waldur_generator.cli.Generator")
    @patch("os.path.exists", return_value=False)
    @patch("sys.argv", ["generate"])
    def test_makedirs_error_propagates(self, mock_exists, mock_generator_class):
        """Test that os.makedirs errors are propagated."""
        with patch("os.makedirs", side_effect=PermissionError("Permission denied")):
            with pytest.raises(PermissionError, match="Permission denied"):
                cli.main()


class TestCliHelp:
    """Test CLI help and argument descriptions."""

    def test_argument_parser_configuration(self):
        """Test that argument parser is configured correctly."""
        with patch("sys.argv", ["generate", "--help"]):
            with pytest.raises(SystemExit):  # --help causes sys.exit(0)
                cli.main()

    @patch("argparse.ArgumentParser.parse_args")
    def test_parser_arguments_defined(self, mock_parse_args):
        """Test that all expected arguments are defined."""
        # Mock the parse_args to avoid actual parsing
        mock_args = Mock()
        mock_args.config = "test_config.yaml"
        mock_args.api_spec = "test_api.yaml"
        mock_args.output_dir = "test_output"
        mock_parse_args.return_value = mock_args

        with patch("ansible_waldur_generator.cli.Generator"):
            with patch("os.path.exists", return_value=True):
                cli.main()

        # Verify parse_args was called (meaning parser was set up)
        mock_parse_args.assert_called_once()


class TestCliRealWorldScenarios:
    """Test CLI with real-world scenarios."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("ansible_waldur_generator.cli.Generator")
    def test_end_to_end_cli_flow(self, mock_generator_class):
        """Test complete CLI flow from argument parsing to generation."""
        # Create test input files
        config_file = os.path.join(self.temp_dir, "config.yaml")
        api_spec_file = os.path.join(self.temp_dir, "api.yaml")
        output_dir = os.path.join(self.temp_dir, "output")

        test_config = {
            "collections": [
                {
                    "namespace": "test",
                    "name": "collection",
                    "version": "1.0.0",
                    "modules": [],
                }
            ]
        }
        test_api_spec = {"openapi": "3.0.0", "paths": {}}

        with open(config_file, "w") as f:
            yaml.dump(test_config, f)
        with open(api_spec_file, "w") as f:
            yaml.dump(test_api_spec, f)

        # Mock Generator
        mock_generator = Mock()
        mock_generator_class.from_files.return_value = mock_generator

        # Run CLI with test arguments
        with patch(
            "sys.argv",
            [
                "generate",
                "--config",
                config_file,
                "--api-spec",
                api_spec_file,
                "--output-dir",
                output_dir,
            ],
        ):
            with patch("builtins.print") as mock_print:
                cli.main()

        # Verify the complete flow
        mock_generator_class.from_files.assert_called_once_with(
            config_path=config_file, api_spec_path=api_spec_file
        )
        mock_generator.generate.assert_called_once_with(output_dir=output_dir)
        mock_print.assert_called_with("\nGeneration complete.")

        # Verify output directory was created
        assert os.path.exists(output_dir)

    @patch("ansible_waldur_generator.cli.Generator")
    def test_relative_paths_handling(self, mock_generator_class):
        """Test CLI handles relative paths correctly."""
        mock_generator = Mock()
        mock_generator_class.from_files.return_value = mock_generator

        with patch(
            "sys.argv",
            [
                "generate",
                "--config",
                "./config.yaml",
                "--api-spec",
                "../api.yaml",
                "--output-dir",
                "output",
            ],
        ):
            with patch("os.path.exists", return_value=True):
                cli.main()

        # Verify relative paths are passed through correctly
        mock_generator_class.from_files.assert_called_once_with(
            config_path="./config.yaml", api_spec_path="../api.yaml"
        )
        mock_generator.generate.assert_called_once_with(output_dir="output")
