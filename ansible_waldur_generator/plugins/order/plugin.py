from ansible_waldur_generator.interfaces.plugin import BasePlugin
from ansible_waldur_generator.plugins.order.builder import OrderContextBuilder
from ansible_waldur_generator.plugins.order.config import OrderModuleConfig
from ansible_waldur_generator.plugins.order.parser import OrderConfigParser


class OrderPlugin(BasePlugin):
    """Plugin for handling 'order' module types."""

    def get_type_name(self) -> str:
        return "order"

    def get_parser(self, module_key, raw_config, api_parser, collector):
        return OrderConfigParser(module_key, raw_config, api_parser, collector)

    def get_builder(self, module_config: OrderModuleConfig, api_parser, collector):
        return OrderContextBuilder(module_config, api_parser, collector)
