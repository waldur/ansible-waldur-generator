"""Checks on the shipped generator_config.yaml itself.

Most tests here exercise the generator against synthetic config. These assert
things about the *real* config that a reviewer cannot see by reading either the
generator or the backend alone, because the invariant spans both.
"""

from pathlib import Path

import yaml

CONFIG = Path(__file__).parents[3] / "inputs" / "generator_config.yaml"


def load_modules():
    """Return {module name: module config} across every collection."""
    config = yaml.safe_load(CONFIG.read_text())
    modules = {}
    for collection in config.get("collections", []):
        for module in collection.get("modules", []):
            modules[module["name"]] = module
    return modules


def test_network_rbac_policy_composite_key_matches_backend_uniqueness():
    """The lookup key must mirror NetworkRBACPolicy's unique_together.

    Waldur keys an RBAC policy on (network, target_tenant, policy_type), and so
    does Neutron -- (object, target, action). Keyed on the pair alone, a request
    for ``access_as_external`` matched an existing ``access_as_shared`` row for
    the same network and target, so the module reported ``changed=false`` and
    created nothing: a share the playbook asked for silently never existed.

    ``policy_type`` carries a schema default, so adding it to the key does not
    make it a required parameter -- the runner always finds a value.
    """
    module = load_modules()["network_rbac_policy"]
    assert module["composite_keys"] == ["network", "target_tenant", "policy_type"]


def test_composite_keys_are_declared_parameters():
    """Every composite key must be resolvable or a plain parameter.

    The runner maps each key through ``check_filter_keys`` when it is a
    resolver, and otherwise sends it as-is. A key that is neither would be sent
    as an unknown query parameter, which the API ignores -- turning the
    existence check into a broader match than intended and making the module
    claim a resource already exists when it does not.
    """
    for name, module in load_modules().items():
        for key in module.get("composite_keys") or []:
            resolvers = module.get("resolvers") or {}
            # 'name' and 'uuid' are always present on a crud module; anything
            # else must either resolve or be a documented plain field.
            assert key in resolvers or key in {"name", "uuid", "policy_type"}, (
                f"{name}: composite key '{key}' is neither a resolver nor a "
                "known plain parameter"
            )
