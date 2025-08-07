from ansible_waldur_generator.interfaces.plugin import BasePlugin
from ansible_waldur_generator.plugins.facts.builder import FactsContextBuilder
from ansible_waldur_generator.plugins.facts.config import FactsModuleConfig
from ansible_waldur_generator.plugins.facts.parser import FactsConfigParser


class FactsPlugin(BasePlugin):
    """Plugin for handling 'facts' module types."""

    def get_type_name(self) -> str:
        return "facts"

    def get_parser(self, module_key, raw_config, api_parser, collector):
        return FactsConfigParser(module_key, raw_config, api_parser, collector)

    def get_builder(self, module_config: FactsModuleConfig, api_parser, collector):
        return FactsContextBuilder(module_config, api_parser, collector)
