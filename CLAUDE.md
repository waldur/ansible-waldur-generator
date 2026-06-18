# ansible-waldur-generator

A **code generator** (Python) that turns the Waldur OpenAPI schema + a YAML config into a
self-contained **Ansible Collection**. The published collection lives on
[Ansible Galaxy](https://galaxy.ansible.com/ui/repo/published/waldur/); the generated code itself
is **not** committed here — it is a build artifact.

> You are almost always editing the **generator**, not generated modules. Never hand-edit anything
> under `outputs/` — it is regenerated and thrown away.

## Source vs. output

| Path | Role |
|------|------|
| `ansible_waldur_generator/` | The generator (edit here) |
| `inputs/generator_config.yaml` | Defines collections + modules; **collection version is a manual literal here** |
| `inputs/waldur_api.yaml` | The Waldur OpenAPI schema — the source of truth for module content |
| `outputs/` | Generated collections — **gitignored**, built fresh by `uv run ansible-waldur-generator` |

Because `outputs/` is gitignored and the content is schema-driven, changes to the generated modules
leave **no git diff and no changelog entry** in this repo. There is no changelog tooling here at
all (no `CHANGELOG.md`, no git tags, version pinned at `0.0.1` in `pyproject.toml`). See the
workspace-level discussion in `../CLAUDE.md`; if you add changelog support, the schema-diff approach
(diff the generated module/param set between schema revisions) is the one that actually captures
these changes.

## Architecture

The `Generator` is **type-agnostic**: it loops collections → modules and delegates each module to a
**plugin** chosen by the module's `plugin:` key. Plugins are discovered via `pyproject.toml` entry
points (`[project.entry-points."ansible_waldur_generator"]`).

Five plugins live under `ansible_waldur_generator/plugins/<type>/`:

| Plugin | Purpose |
|--------|---------|
| `crud` | Simple create/update/delete resources |
| `order` | Async marketplace orders (with dependency-filtered resolvers) |
| `facts` | Read-only fact-gathering modules |
| `actions` | Standalone API actions on existing resources |
| `link` | Linking resources (e.g. volume attachment) |

Each plugin directory has the same three files:

- **`config.py`** — Pydantic model validating that plugin's YAML config.
- **`plugin.py`** — *generation-time* logic; implements `BasePlugin.generate()`, builds the
  `argument_spec`, docs, examples, and the runner context.
- **`runner.py`** — *runtime* logic shipped inside the module; inherits `BaseRunner`, uses
  `ParameterResolver`.

Shared contracts live in `ansible_waldur_generator/interfaces/` (`plugin.py`, `runner.py`,
`resolver.py`, `command.py`).

### Two runtime ideas worth knowing before editing a plugin

- **Self-contained collections**: the generator copies the plugin's `runner.py` + a shared
  `base_runner.py` into the collection's `plugins/module_utils/` and **rewrites their imports**.
  Generated modules are thin wrappers calling their runner.
- **Plan-and-execute**: runners build a list of `Command` objects (planning, no side effects) then
  execute them. This is what makes Ansible check-mode correct and emits the `commands` audit key.
- **ParameterResolver**: converts user-friendly names/UUIDs into API URLs, with recursive
  resolution, response caching, and `filter_by` dependency filtering (e.g. flavors filtered by an
  offering's tenant). The `order` plugin leans on this heaviest.

Full deep-dive (resolvers, idempotency normalization, "how to add a plugin") lives in
`docs/plugins.md` and `docs/best-practices.md` — read those before non-trivial plugin work.

### Adding a plugin

New dir `plugins/<type>/` with `config.py` + `plugin.py` + `runner.py`, then register it in the
`pyproject.toml` entry points and run `uv sync` so the `PluginManager` picks it up. No change to
`generator.py` is needed.

## Commands

```bash
uv sync                                   # install / refresh (re-run after editing entry points)
uv run ansible-waldur-generator           # generate collections into outputs/

# Tests
uv run pytest ansible_waldur_generator/tests/unit/
uv run pytest ansible_waldur_generator/tests/e2e/ --vcr-record=none   # replays VCR cassettes

# Lint (ruff-format + ruff + pymarkdown)
uv run pre-commit run --all
```

Python 3.11+ (CI also smoke-tests the generated collection under 3.9). E2E tests use `pytest-vcr`
cassettes under `tests/e2e/cassettes/`.

## Conventions

- **Branch / remote**: default branch `main`, GitLab (`code.opennodecloud.com:waldur/ansible-waldur-generator`).
- **Commits**: `Description [WAL-1234]` (ticket IDs are used, e.g. `[WAL-9970]`, `[ONS-1190]`).
- **Don't hardcode** service- or field-specific behavior in the generator core — drive it from
  `generator_config.yaml` (resolvers, `base_operation_id`, etc.).
- **Lint must pass** before pushing (`pre-commit run --all`), and the generated collection must
  still build/test (CI `Generate Collection` → `Test Collection 3.11`/`3.9`).
</content>
</invoke>
