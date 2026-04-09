"""
damage — Data models for damage pipeline results.

DamageStep:    Single step in a damage pipeline branch: carries value, min/max
               range, formula string, and Hercules source reference.
DamageResult:  Full output of one pipeline branch (normal or crit): aggregates
               DamageSteps and holds the final PMF (probability mass function).
BattleResult:  Top-level result returned by BattlePipeline.calculate(); carries
               normal, crit, and all auxiliary branches (katar, dual-wield, procs,
               second hits) plus DPS and timing fields.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.models.attack_definition import AttackDefinition


@dataclass
class DamageStep:
    """Single step in the damage pipeline – includes min/max/avg and source-accurate debug strings."""
    name: str
    value: int          # avg — used by GUI display
    min_value: int = 0  # populated when variance is known; 0 = informational step only
    max_value: int = 0  # populated when variance is known; 0 = informational step only
    multiplier: float = 1.0
    note: str = ""
    formula: str = ""          # e.g. "status.batk + weapon.atk + refine_bonus"
    hercules_ref: str = ""     # e.g. "battle.c: battle_calc_base_damage2 (pre-renewal)"

    def __post_init__(self):
        # Auto-fill only when BOTH are 0, meaning neither was explicitly provided
        # (informational step). If min_value=0 but max_value≠0, the zero is a
        # legitimate minimum damage value (e.g. size fix flooring a low-DEX roll).
        if self.min_value == 0 and self.max_value == 0:
            self.min_value = self.value
            self.max_value = self.value
        if not self.formula:
            self.formula = "N/A (legacy step)"
        if not self.hercules_ref:
            self.hercules_ref = "N/A (legacy step)"


@dataclass
class DamageResult:
    """Full damage result – steps carry formula + hercules_ref for Treeview debugging.

    pmf: populated by the pipeline as it runs through modifiers (dict[int, float]).
    min_damage / max_damage / avg_damage: derived from pmf at the end of each pipeline
    branch via pmf_stats(result.pmf); do not set these manually mid-pipeline.
    """
    min_damage: int = 0
    max_damage: int = 0
    avg_damage: int = 0
    crit_chance: float = 0.0
    hit_chance: float = 0.0
    steps: List[DamageStep] = field(default_factory=list)
    pmf: dict = field(default_factory=dict)  # dict[int, float], populated by pipeline

    def add_step(self,
                 name: str,
                 value: int,
                 min_value: int = 0,
                 max_value: int = 0,
                 multiplier: float = 1.0,
                 note: str = "",
                 formula: str = "",
                 hercules_ref: str = ""):
        """Add step with full debug strings and optional min/max range."""
        self.steps.append(DamageStep(
            name=name,
            value=value,
            min_value=min_value,
            max_value=max_value,
            multiplier=multiplier,
            note=note,
            formula=formula,
            hercules_ref=hercules_ref,
        ))


@dataclass
class BattleResult:
    """Full output of BattlePipeline.calculate() — carries both normal and crit branches.

    normal:      Always present. Full DamageResult for the non-crit hit path.
    crit:        None when the skill/attack is ineligible for crits (e.g. SM_BASH).
                 Otherwise a full DamageResult for the crit hit path.
    crit_chance: Probability (percent, 0-100) that a single hit is a crit.
                 0.0 when crit is None.
    hit_chance:  Computed by calculate_hit_chance() in hit_chance.py.
                 80 + player_HIT - mob_FLEE, clamped to [min_hitrate, max_hitrate].
                 Source: battle.c:4469/5024 (#ifndef RENEWAL).
    """
    normal: "DamageResult" = field(default_factory=lambda: DamageResult())
    crit: Optional["DamageResult"] = None
    crit_chance: float = 0.0
    hit_chance: float = 100.0      # basic hit% (80 + HIT - FLEE, clamped to [min, max])
    perfect_dodge: float = 0.0    # target's perfect dodge chance (luk+10)/10 %
    magic: Optional["DamageResult"] = None  # BF_MAGIC result populated by MagicPipeline (magic_pipeline.py); mirrored to normal for GUI display
    # Katar normal-attack second hit (battle.c:5941-5952, #ifndef RENEWAL).
    # Computed from final post-pipeline PMF: damage2 = max(1, damage * (1 + TF_DOUBLE*2) // 100).
    # katar_second = second hit of non-crit branch; katar_second_crit = second hit of crit branch.
    katar_second: Optional["DamageResult"] = None
    katar_second_crit: Optional["DamageResult"] = None
    # TF_DOUBLE (Knife) / GS_CHAINACTION (Revolver) proc branches.
    # proc_chance: percent probability per auto-attack swing (0 = not eligible).
    # double_hit / double_hit_crit: full 2-hit pipeline result for the proc swing.
    # Crit and proc are mutually exclusive (battle.c:4926).
    proc_chance: float = 0.0
    double_hit: Optional["DamageResult"] = None
    double_hit_crit: Optional["DamageResult"] = None
    # PS: Bowling Bash / Brandish Spear — second hit modelled as a separate pipeline instance.
    # Second hit strips SC_LEXAETERNA (Lex Aeterna doubles first hit only).
    # second_hit = non-crit branch; second_hit_crit = crit branch (None when not crit-eligible).
    second_hit: Optional["DamageResult"] = None
    second_hit_crit: Optional["DamageResult"] = None
    # Dual-wield left-hand branches (normal-attack only; skill_id == 0).
    # None when not dual-wielding. Independent element + forge chain from LH weapon.
    lh_normal: Optional["DamageResult"] = None
    lh_crit: Optional["DamageResult"] = None
    # Proc branches — keyed by PROC_* constants from core.calculators.proc_keys.
    # Each entry is a DamageResult for that proc type; proc_chances holds its per-swing %.
    # Display and DPS contribution handled by SummarySection (gui/sections/summary_section.py) iterating these dicts.
    proc_branches: Dict[str, "DamageResult"] = field(default_factory=dict)
    proc_chances:  Dict[str, float]         = field(default_factory=dict)
    # Human-readable labels for dynamic proc keys (e.g. autocast_atk_0, autocast_skill_2).
    # Populated by _apply_item_autocasts() in battle_pipeline.py as f"{skill_description} Lv.{level}".
    # SummarySection (gui/sections/summary_section.py) prefers this over _PROC_DISPLAY_NAMES for dynamic keys.
    proc_labels: Dict[str, str] = field(default_factory=dict)
    # DPS stat: Σ(chance_i × damage_i) / Σ(chance_i × delay_i) × 1000  (dmg/s)
    dps: float = 0.0
    # Full attack distribution used to compute dps. Stored on BattleResult so
    # future branches (skills, procs) can append without modifying this class.
    attacks: List["AttackDefinition"] = field(default_factory=list)
    # Timing: minimum period between consecutive uses (ms).
    # Auto-attack: adelay = 2 × amotion.  Skill: max(cast_ms + delay_ms, amotion).
    # Source: status.c:2134 (adelay = 2×amotion); unit.c:1846 (period = max(cast+delay, amotion))
    period_ms: float = 0.0
    # True when the damage pipeline has a confirmed skill ratio for the selected skill.
    # False for BF_WEAPON skills not yet in IMPLEMENTED_BF_WEAPON_SKILLS.
    # When False, DPS is hidden in the GUI (timing/Speed is still shown).
    dps_valid: bool = True
