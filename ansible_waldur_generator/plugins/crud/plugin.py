from ansible_waldur_generator.interfaces.plugin import BasePlugin
from ansible_waldur_generator.plugins.crud.builder import CrudContextBuilder
from ansible_waldur_generator.plugins.crud.parser import CrudConfigParser


class CrudPlugin(BasePlugin):
    """
    Crud plugin for Ansible Waldur Generator.
    This plugin handles the parsing and building of CRUD configurations.
    """

    def get_type_name(self) -> str:
        return "crud"

    def get_parser(self, module_key, raw_config, op_map, collector):
        return CrudConfigParser(module_key, raw_config, op_map, collector)

    def get_builder(self, module_config, api_spec_data, collector):
        return CrudContextBuilder(module_config, api_spec_data, collector)

    def get_template_name(self) -> str:
        return "crud_module.py.j2"
