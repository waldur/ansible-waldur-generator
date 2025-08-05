import importlib.metadata
import logging
from typing import Dict, Optional, cast

from .interfaces.plugin import BasePlugin

# The unique name of our plugin entry point group.
ENTRY_POINT_GROUP = "ansible_waldur_generator"

logger = logging.getLogger(__name__)


class PluginManager:
    """Discovers, loads, and manages all available generator plugins via entry points."""

    def __init__(self):
        self.plugins: Dict[str, BasePlugin] = {}
        self._load_plugins()

    def _load_plugins(self):
        """
        Discovers and loads plugins using importlib.metadata.
        """
        # Get all entry points registered under our group name.
        entry_points = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)

        for entry_point in entry_points:
            try:
                plugin_class = entry_point.load()
                plugin_instance = cast(BasePlugin, plugin_class())
                type_name = plugin_instance.get_type_name()
                self.plugins[type_name] = plugin_instance
                logger.info(
                    "Registered plugin '%s' for type: '%s'", entry_point.name, type_name
                )

            except Exception as e:
                logger.warning("Could not load plugin '%s': %s", entry_point.name, e)

    def get_plugin(self, module_type: str) -> Optional[BasePlugin]:
        """Returns the registered plugin for a given module type."""
        return self.plugins.get(module_type)
