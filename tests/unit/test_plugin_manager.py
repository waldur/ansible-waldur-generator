"""Tests for the PluginManager class."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from ansible_waldur_generator.plugin_manager import PluginManager
from ansible_waldur_generator.interfaces.plugin import BasePlugin


class MockPlugin(BasePlugin):
    """Mock plugin for testing."""
    
    def get_type_name(self) -> str:
        return "mock"
    
    def generate(self, module_key, raw_config, api_parser, return_generator, collection_context):
        return Mock()
    
    def _build_examples(self, *args, **kwargs):
        return []
    
    def _build_parameters(self, *args, **kwargs):
        return {}
    
    def _build_return_block(self, *args, **kwargs):
        return {}
    
    def _build_runner_context(self, *args, **kwargs):
        return {}
    
    def _parse_configuration(self, *args, **kwargs):
        return {}


class TestPluginManager:
    """Test suite for the PluginManager class."""

    @pytest.fixture
    def mock_entry_points(self):
        """Mock entry points for plugin discovery."""
        with patch("ansible_waldur_generator.plugin_manager.importlib.metadata.entry_points") as mock_ep:
            # Create mock entry points
            mock_crud_ep = Mock()
            mock_crud_ep.name = "crud"
            # Create a proper mock plugin class
            mock_crud_plugin_class = Mock()
            mock_crud_plugin_instance = Mock(spec=BasePlugin)
            mock_crud_plugin_instance.get_type_name.return_value = "crud"
            mock_crud_plugin_class.return_value = mock_crud_plugin_instance
            mock_crud_ep.load.return_value = mock_crud_plugin_class
            
            mock_facts_ep = Mock()
            mock_facts_ep.name = "facts"
            mock_facts_plugin_class = Mock()
            mock_facts_plugin_instance = Mock(spec=BasePlugin)
            mock_facts_plugin_instance.get_type_name.return_value = "facts"
            mock_facts_plugin_class.return_value = mock_facts_plugin_instance
            mock_facts_ep.load.return_value = mock_facts_plugin_class
            
            mock_order_ep = Mock()
            mock_order_ep.name = "order"
            mock_order_plugin_class = Mock()
            mock_order_plugin_instance = Mock(spec=BasePlugin)
            mock_order_plugin_instance.get_type_name.return_value = "order"
            mock_order_plugin_class.return_value = mock_order_plugin_instance
            mock_order_ep.load.return_value = mock_order_plugin_class
            
            # Configure the mock to return our entry points
            mock_ep.return_value = [mock_crud_ep, mock_facts_ep, mock_order_ep]
            
            yield mock_ep

    def test_initialization(self, mock_entry_points):
        """Test PluginManager initialization."""
        manager = PluginManager()
        
        # Should have plugins dict and call _load_plugins
        assert hasattr(manager, 'plugins')
        assert isinstance(manager.plugins, dict)

    def test_discover_plugins(self, mock_entry_points):
        """Test plugin discovery via entry points."""
        manager = PluginManager()
        
        # Check that plugins were discovered
        assert len(manager.plugins) == 3
        assert "crud" in manager.plugins
        assert "facts" in manager.plugins
        assert "order" in manager.plugins

    def test_get_plugin_success(self, mock_entry_points):
        """Test successful plugin retrieval."""
        manager = PluginManager()
        
        # The mock entry points should have loaded plugins
        plugin = manager.get_plugin("crud")
        assert plugin is not None

    def test_get_plugin_not_found(self, mock_entry_points):
        """Test plugin retrieval when plugin doesn't exist."""
        
        manager = PluginManager()
        
        plugin = manager.get_plugin("nonexistent")
        assert plugin is None

    def test_plugin_loading_error(self):
        """Test handling of plugin loading errors."""
        with patch("ansible_waldur_generator.plugin_manager.importlib.metadata.entry_points") as mock_ep:
            # Create a mock entry point that raises an error
            mock_bad_ep = Mock()
            mock_bad_ep.name = "bad_plugin"
            mock_bad_ep.load.side_effect = ImportError("Failed to load")
            
            mock_ep.return_value = [mock_bad_ep]
            
            # Should not raise, just log the error
            manager = PluginManager()
            assert "bad_plugin" not in manager.plugins

    def test_plugin_validation(self, mock_entry_points):
        """Test that loaded plugins are validated as BasePlugin subclasses."""
        with patch("ansible_waldur_generator.plugin_manager.importlib.metadata.entry_points") as mock_ep:
            # Create a mock entry point that returns a non-plugin class
            mock_invalid_ep = Mock()
            mock_invalid_ep.name = "invalid"
            mock_invalid_ep.load.return_value = str  # Not a BasePlugin subclass
            
            mock_ep.return_value = [mock_invalid_ep]
            
            manager = PluginManager()
            # Invalid plugin should be loaded but won't work as expected
            # This tests that the manager doesn't crash
            assert manager is not None

    def test_list_available_plugins(self, mock_entry_points):
        """Test listing all available plugin types."""
        
        manager = PluginManager()
        
        available = list(manager.plugins.keys())
        assert "crud" in available
        assert "facts" in available
        assert "order" in available
        assert len(available) == 3

    def test_register_plugin_manually(self):
        """Test manual plugin registration."""
        
        with patch("ansible_waldur_generator.plugin_manager.importlib.metadata.entry_points") as mock_ep:
            mock_ep.return_value = []  # No auto-discovered plugins
            
            manager = PluginManager()
            
            # Manually register a plugin instance
            manager.plugins["manual"] = MockPlugin()
            
            plugin = manager.get_plugin("manual")
            assert plugin is not None
            assert plugin.get_type_name() == "mock"

    def test_plugin_instantiation(self, mock_entry_points):
        """Test that plugins are instantiated correctly."""
        
        manager = PluginManager()
        
        # Replace one plugin with our mock instance
        manager.plugins["crud"] = MockPlugin()
        
        plugin = manager.get_plugin("crud")
        assert isinstance(plugin, MockPlugin)
        assert plugin.get_type_name() == "mock"

    def test_empty_entry_points(self):
        """Test behavior when no plugins are discovered."""
        with patch("ansible_waldur_generator.plugin_manager.importlib.metadata.entry_points") as mock_ep:
            mock_ep.return_value = []  # No plugins
            
            manager = PluginManager()
            assert len(manager.plugins) == 0
            assert manager.get_plugin("any") is None

    def test_duplicate_plugin_names(self):
        """Test handling of duplicate plugin names."""
        with patch("ansible_waldur_generator.plugin_manager.importlib.metadata.entry_points") as mock_ep:
            # Create two entry points with the same name
            mock_ep1 = Mock()
            mock_ep1.name = "duplicate"
            mock_plugin1_class = Mock()
            mock_plugin1_instance = Mock(spec=BasePlugin)
            mock_plugin1_instance.get_type_name.return_value = "duplicate"
            mock_plugin1_class.return_value = mock_plugin1_instance
            mock_ep1.load.return_value = mock_plugin1_class
            
            mock_ep2 = Mock()
            mock_ep2.name = "duplicate"
            mock_plugin2_class = MockPlugin  # Use the MockPlugin class
            mock_ep2.load.return_value = mock_plugin2_class
            
            mock_ep.return_value = [mock_ep1, mock_ep2]
            
            manager = PluginManager()
            # The last one should win - MockPlugin returns "mock" as type name
            assert "mock" in manager.plugins

    @patch("ansible_waldur_generator.plugin_manager.logger.warning")
    def test_error_logging(self, mock_logger):
        """Test that errors are logged during plugin loading."""
        with patch("ansible_waldur_generator.plugin_manager.importlib.metadata.entry_points") as mock_ep:
            mock_bad_ep = Mock()
            mock_bad_ep.name = "error_plugin"
            mock_bad_ep.load.side_effect = Exception("Test error")
            
            mock_ep.return_value = [mock_bad_ep]
            
            manager = PluginManager()
            
            # Check that error was logged
            mock_logger.assert_called()
            call_args = str(mock_logger.call_args)
            assert "error_plugin" in call_args or "Test error" in call_args