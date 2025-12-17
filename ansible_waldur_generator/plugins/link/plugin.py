from typing import Any, Dict, List

from ansible_waldur_generator.api_parser import ApiSpecParser
from ansible_waldur_generator.helpers import AUTH_FIXTURE, AUTH_OPTIONS
from ansible_waldur_generator.interfaces.plugin import BasePlugin
from ansible_waldur_generator.models import AnsibleModuleParams
from ansible_waldur_generator.plugins.link.config import LinkModuleConfig
from ansible_waldur_generator.schema_parser import ReturnBlockGenerator


class LinkPlugin(BasePlugin):
    """Plugin for generating modules that manage a link between two resources."""

    def get_type_name(self) -> str:
        return "link"

    def _parse_configuration(
        self,
        module_key: str,
        raw_config: Dict[str, Any],
        api_parser: ApiSpecParser,
    ) -> LinkModuleConfig:
        """Parses the config, resolving all operationId strings and resolvers."""

        def parse_resource_config(key: str) -> dict:
            conf = raw_config[key]
            if "retrieve_op" in conf:
                conf["retrieve_op"] = api_parser.get_operation(conf["retrieve_op"])
            return conf

        raw_config["source"] = parse_resource_config("source")
        raw_config["target"] = parse_resource_config("target")

        raw_config["link_op"] = api_parser.get_operation(raw_config["link_op"])
        raw_config["unlink_op"] = api_parser.get_operation(raw_config["unlink_op"])

        # Use the powerful shared parser for resolvers
        raw_config["resolvers"] = self._parse_resolvers(raw_config, api_parser)

        # Validate and return the final configuration object
        return LinkModuleConfig(**raw_config)

    def _build_parameters(
        self, module_config: LinkModuleConfig, api_parser: ApiSpecParser
    ) -> AnsibleModuleParams:
        """Builds the Ansible module's parameters."""
        conf = module_config
        params: AnsibleModuleParams = {
            **AUTH_OPTIONS,
            "state": {
                "description": "Should the link be present (e.g., attached) or absent (e.g., detached).",
                "choices": ["present", "absent"],
                "default": "present",
                "type": "str",
            },
            conf.source.param: {
                "description": f"The name or UUID of the {conf.source.resource_type}.",
                "type": "str",
                "required": True,
            },
            conf.target.param: {
                "description": f"The name or UUID of the {conf.target.resource_type}.",
                "type": "str",
                "required": True,
            },
        }

        for p_conf in conf.link_params:
            params[p_conf.name] = {
                "description": p_conf.description,
                "type": p_conf.type,
                "required": p_conf.required,
            }

        # Add context parameters from resolvers.
        for name in conf.resolvers:
            if name not in params and name not in [
                conf.source.param,
                conf.target.param,
            ]:
                params[name] = {
                    "description": f"The name or UUID of the parent {name} for filtering.",
                    "type": "str",
                    "required": False,
                }
        return params

    def _build_return_block(
        self,
        module_config: LinkModuleConfig,
        return_generator: ReturnBlockGenerator,
    ) -> Dict[str, Any]:
        """Builds the RETURN block based on the source resource's retrieve operation."""
        if not module_config.source.retrieve_op:
            return {}

        op_spec = module_config.source.retrieve_op.raw_spec
        return_content = return_generator.generate_for_operation(
            op_spec, module_config.source.resource_type
        )
        if not return_content:
            return {}
        return {
            "resource": {
                "description": f"The state of the {module_config.source.resource_type} after the operation.",
                "type": "dict",
                "returned": "on success",
                "contains": return_content,
            }
        }

    def _build_examples(
        self,
        module_config: LinkModuleConfig,
        module_name: str,
        collection_namespace: str,
        collection_name: str,
        schema_parser: ReturnBlockGenerator,
    ) -> List[Dict[str, Any]]:
        """Generates examples for attaching and detaching."""
        fqcn = f"{collection_namespace}.{collection_name}.{module_name}"
        s_param = module_config.source.param
        t_param = module_config.target.param

        # --- MODIFIED ---
        # Build a base set of parameters including the new context resolvers.
        base_params = {
            s_param: f"My-{s_param}",
            t_param: f"My-{t_param}",
            **AUTH_FIXTURE,
        }
        for name in module_config.resolvers:
            if name not in base_params and name not in [s_param, t_param]:
                base_params[name] = f"My-Parent-{name.capitalize()}"

        present_params = {"state": "present", **base_params}
        for p in module_config.link_params:
            present_params[p.name] = schema_parser._generate_sample_value(
                p.name, {"type": p.type}, ""
            )

        absent_params = {"state": "absent", **base_params}

        return [
            {
                "name": f"Attach a {module_config.source.resource_type} to a {module_config.target.resource_type}",
                "hosts": "localhost",
                "tasks": [{"name": "Link resources", fqcn: present_params}],
            },
            {
                "name": f"Detach a {module_config.source.resource_type} from a {module_config.target.resource_type}",
                "hosts": "localhost",
                "tasks": [{"name": "Unlink resources", fqcn: absent_params}],
            },
        ]

    def _build_runner_context(
        self, module_config: LinkModuleConfig, api_parser: ApiSpecParser
    ) -> dict:
        """Assembles the context for the LinkRunner."""
        conf = module_config

        resolvers_data = {}
        for name, resolver in conf.resolvers.items():
            resolvers_data[name] = {
                "url": resolver.list_operation.path,
                "error_message": resolver.error_message,
                "filter_by": [f.model_dump() for f in resolver.filter_by],
                "name_query_param": resolver.name_query_param,
            }

        sorted_resolver_names = self._get_sorted_resolvers(conf.resolvers)

        return {
            "resource_type": conf.resource_type,
            "source": conf.source.model_dump(exclude={"retrieve_op"}),
            "target": conf.target.model_dump(exclude={"retrieve_op"}),
            "link_op_path": conf.link_op.path,
            "unlink_op_path": conf.unlink_op.path,
            "link_check_key": conf.link_check_key,
            "link_param_names": [p.name for p in conf.link_params],
            "resolvers": resolvers_data,
            "resolver_order": sorted_resolver_names,
        }
