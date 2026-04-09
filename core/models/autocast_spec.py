"""
AutocastSpec — one item autocast bonus parsed from an item script.

Three variant sources:
  bonus3 bAutoSpell        → attack-time proc (src_skill_id=None, when_hit=False)
  bonus4 bAutoSpell        → same, with explicit BF_* flag (flag ignored; treated as default)
  bonus3 bAutoSpellWhenHit → proc when player is hit (when_hit=True; parsed but not wired into outgoing damage)
  bonus4 bAutoSpellWhenHit → same with explicit flag
  bonus4 bAutoSpellOnSkill → proc when src_skill is used (src_skill_id set, when_hit=False)
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class AutocastSpec:
    skill_id: int             # proc spell ID (resolved from name at aggregation time)
    skill_level: int          # fixed proc level (no level variance unlike SA_AUTOSPELL)
    chance_per_mille: int     # raw rate field (e.g. 100 → 10%)
    src_skill_id: int | None = None  # bAutoSpellOnSkill: trigger skill ID (None = attack-time)
    when_hit: bool = False    # bAutoSpellWhenHit: parse only, not wired into outgoing pipeline
