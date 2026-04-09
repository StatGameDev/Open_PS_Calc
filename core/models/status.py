"""
StatusData — computed secondary stats for the player side in damage calculations.

Output of StatusCalculator (status_calculator.py); consumed by the BF_WEAPON and
BF_MAGIC pipelines and the GUI display layer. Mirrors struct status_data fields
from battle.c / status.c.
"""
from dataclasses import dataclass, field

@dataclass
class StatusData:
    str: int = 0
    agi: int = 0
    vit: int = 0
    int_: int = 0
    dex: int = 0
    luk: int = 0

    batk: int = 0      # Base ATK
    def_: int = 0      # Hard DEF (def1)
    def2: int = 0      # Soft DEF (vit_def)
    cri: int = 0       # in 0.1% units (100 = 10.0%)
    hit: int = 0
    flee: int = 0
    flee2: int = 0
    aspd: float = 0.0
    max_hp: int = 0
    max_sp: int = 0

    matk_min: int = 0  # Pre-renewal MATK min (status.c:3783 #else not RENEWAL)
    matk_max: int = 0  # Pre-renewal MATK max (status.c:3790 #else not RENEWAL)
    mdef: int = 0      # Hard MDEF (from bMdef scripts)
    mdef2: int = 0     # Soft MDEF = int_ + vit//2 (status.c:3867 #else not RENEWAL)

    def_percent: int = 100  # st->def_percent: multiplier on vit_def for PC targets (status.c:3872, battle.c:1492)
                            # SC_ANGELUS adds val2=5*level (pre-renewal); default 100 = no scaling

    # SC_POEMBRAGI (BA_POEMBRAGI) — display-only; no action speed simulation in this calculator.
    # skill.c:17253 / 17486 — both values are percentages (e.g. 30 = 30% reduction)
    cast_time_reduction_pct: int = 0
    after_cast_delay_reduction_pct: int = 0

    # SC-based cast time increase — separate multiplicative step after Bragi/Suffragium.
    # Mirrors SC_SLOWCAST pattern in skill_castfix_sc (skill.c:17242): time += time * val2 / 100.
    # SC_PS_HYPOTHERMIA contributes +20 here.
    cast_time_penalty_pct: int = 0

    # SC_SERVICEFORYU (DC_SERVICEFORYOU) val3 — SP cost reduction %; display-only.
    # Applied in skill cast cost checks in Hercules; not simulated here.
    sp_cost_reduction_pct: int = 0

    # Natural tick regen (status_calc_regen_pc, status.c:2650–2653, no RENEWAL guard)
    hp_regen: int = 0
    sp_regen: int = 0

    # Source attribution log — emitted by StatusCalculator (status_calculator.py) for each SC/passive/song additive
    # contribution to flat secondary stats (hit, flee, flee2, batk, cri, def, mdef).
    # Schema: sources[stat_key][label] = amount
    # CRI values stored in 0.1% units (native StatusCalculator scale); caller divides by 10 for display.
    sources: dict = field(default_factory=dict)