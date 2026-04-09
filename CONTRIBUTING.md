# Contributing to PS Calc

## Reporting bugs

Open an issue with:
- Skill name and level
- All relevant input values (stats, gear, buffs, target)
- Expected damage (from server) and actual calculator output

For formula disagreements, a reference to the Hercules source line is ideal but not required.

---

## Pull requests

PRs are welcome. Before opening one:

- Run the existing tests: `python -m pytest tests/`
- Keep changes focused — one fix or feature per PR
- New formula implementations must cite the Hercules source (see *Formula accuracy* below)

---

## Architecture overview

The damage pipeline is split into four paths:

| Path | Entry point |
|---|---|
| BF_WEAPON outgoing | `core/calculators/battle_pipeline.py` |
| BF_MAGIC outgoing | `core/calculators/magic_pipeline.py` |
| Incoming physical | `core/calculators/incoming_physical_pipeline.py` |
| Incoming magic | `core/calculators/incoming_magic_pipeline.py` |

Each pipeline is a sequence of modifier steps in `core/calculators/modifiers/`. Steps receive
a `DamageResult` object (defined in `core/models/damage.py`), append a `DamageStep` describing
what they did, and update `result.running_damage` in place.

Server-specific behaviour (Payon Stories skill ratios, mastery values, custom mechanics) lives
entirely in `core/server_profiles.py` as data tables on the `ServerProfile` dataclass. No
profile name string comparisons appear in the pipeline code.

---

## Formula accuracy

**Hercules is the source of truth.** All pre-renewal formulas are taken from
`Hercules/src/map/battle.c`, `status.c`, `skill.c`, and `pc.c`. The Hercules source
is not included in this repository — see https://github.com/HerculesWS/Hercules.
iro Wiki and RMS sources are not used.

When adding a new damage formula or modifier:

1. Locate the exact function in the Hercules source.
2. Add a comment citing the file and function name: `# battle.c:NNNN function_name`
3. Every magic number must have a source comment. If a constant is not in the cited function,
   trace it to its assignment site and cite that separately.

---

## Code conventions

- Python 3.13. No deprecated APIs.
- GUI: PySide6 + QSS styling in `gui/themes/dark.qss`. No inline style strings.
- No business logic in widget classes — widgets emit signals, core handles calculation.
- `@staticmethod def calculate(...)` for all modifier steps — no instantiation.
- `result.add_step(...)` for every calculation — no silent mutations.
- Pre-renewal only. Ignore code inside `#ifdef RENEWAL` blocks; use `#ifndef RENEWAL` blocks and the `#else` branches of `#ifdef RENEWAL` / `#else` / `#endif` sequences.
