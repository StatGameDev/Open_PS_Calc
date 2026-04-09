"""
Proc branch keys — shared between battle_pipeline.py (writer) and summary_section.py (reader).

Import from here to prevent typo-induced silent failures.
"""

PROC_AUTO_BLITZ    = "auto_blitz"
PROC_AUTOSPELL     = "autospell"
PROC_DOUBLE_BOLT   = "double_bolt"
PROC_HOLY_STRIKE   = "holy_strike"
PROC_TRIPLE_ATTACK = "triple_attack"

# Skills handled by special proc-branch routing in BattlePipeline.calculate()
# (not BF_WEAPON / BF_MAGIC / BF_MISC).  Must appear in combat_controls.py
# _IMPLEMENTED_SKILLS so they show up in the skill dropdown.
IMPLEMENTED_PROC_SKILLS: frozenset[str] = frozenset({"SA_AUTOSPELL"})
