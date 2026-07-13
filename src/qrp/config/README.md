# `qrp.config` — configuration subsystem

## Purpose

Load and validate all platform configuration from YAML into immutable, typed Pydantic v2
models. Validation happens **at load, not at use** (CLAUDE.md §4). No result-affecting value
has a silent default (§9): if it can change research output, it is required, and a missing
key fails loudly at startup.

## Architecture

- `models.py` — the Pydantic model tree rooted at `AppConfig`. Every model is `frozen` and
  forbids unknown keys (typos raise instead of being ignored). Cross-field invariants (e.g.
  tradable ⊆ ingested sessions; cost multipliers include 1×/2×/3×) are enforced by validators.
- `loader.py` — reads a config **directory**, one YAML file per section
  (`costs.yaml` is mandated standalone by §8), assembles them, and validates. All failures
  raise `ConfigError` with the offending path.

## Dependencies

`pydantic>=2`, `pyyaml`. No import-time side effects.

## Public interface

```python
from qrp.config import load_config, AppConfig, ConfigError

config: AppConfig = load_config("config")   # directory path
config.labels.vertical_barrier_bars_h        # -> 30
config.storage.raw_snapshots_dir             # -> Path(data_root) / "raw_snapshots"
```

Exported models: `AppConfig`, `IBKRConnectionConfig`, `SymbolUniverseConfig`, `SymbolSpec`,
`SessionScopeConfig`, `CostModelConfig`, `CommissionConfig`, `LabelSpecConfig`,
`VolatilityEstimatorConfig`, `StoragePathsConfig`, `LoggingConfig`, and the `Session` enum.

## Usage

Configuration lives in the repo `config/` directory: `config.yaml` (metadata) plus
`ibkr.yaml`, `universe.yaml`, `session.yaml`, `costs.yaml`, `labels.yaml`, `storage.yaml`,
`logging.yaml`. Edit those files; the loader validates on the next run.

**Before trusting any result:** set the commission numbers in `config/costs.yaml` to your
actual IBKR account schedule (§8).

## Testing strategy

Unit tests (`tests/config/`) cover required-field enforcement, each validator, unknown-key
rejection, frozen-ness, and every loader failure mode (missing dir/file, empty file,
non-mapping, wrapped validation error). A known-good config is defined once in
`tests/support.py`; negative tests mutate exactly one field.

## Extension points

Add a config domain by adding a model to `models.py`, a field to `AppConfig`, and an entry to
`_SECTION_FILES` in `loader.py`. A new section that changes a storage schema or public
interface requires an ADR (§3).
