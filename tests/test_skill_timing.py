"""Tests for skill timing, per-skill cooldown, and period formula.

Run with:  python -m pytest tests/test_skill_timing.py   (from project root)

Coverage:
  - calculate_skill_timing(): per-skill delayrate (G226), global+per-skill additive stacking,
    PS zero-cast overrides, cooldown not surfacing in effective_delay
  - _skill_period_ms(): vanilla cooldown floor, PS min-period floor, amotion floor,
    Bragi reduces ACD but cannot reduce cooldown floor
  - BattlePipeline.calculate() smoke test with default build + mob 1002
"""
import pytest

from core.calculators.skill_timing import calculate_skill_timing
from core.calculators.battle_pipeline import BattlePipeline, _skill_period_ms
from core.config import BattleConfig
from core.data_loader import loader
from core.models.build import PlayerBuild
from core.models.gear_bonuses import GearBonuses
from core.models.skill import SkillInstance
from core.models.status import StatusData
from core.player_state_builder import resolve_player_state


# ---------------------------------------------------------------------------
# Shared minimal skill_data fixtures
# ---------------------------------------------------------------------------

def _skill_data(cast_time=0, acd=0, cooldown=0, levels=1):
    """Return a minimal skill_data dict with uniform timing across all levels."""
    return {
        "cast_time":             [cast_time] * levels,
        "after_cast_act_delay":  [acd]       * levels,
        "cool_down":             [cooldown]  * levels,
        "cast_time_options":     [],
        "skill_delay_options":   [],
    }

_DEFAULT_STATUS = StatusData(dex=50, agi=50, aspd=150.0)
_DEFAULT_GB     = GearBonuses()


# ---------------------------------------------------------------------------
# calculate_skill_timing — per-skill delayrate (G226)
# ---------------------------------------------------------------------------

def test_per_skill_delayrate_reduces_target_skill():
    """bonus2 bDelayrate,SKILL,-10 reduces ACD of that skill by 10%."""
    gb = GearBonuses(skill_delayrate={"MG_SOULSTRIKE": -10})
    _, delay = calculate_skill_timing(
        "MG_SOULSTRIKE", 5, _skill_data(acd=1000, levels=10), _DEFAULT_STATUS, gb, {}
    )
    assert delay == 900


def test_per_skill_delayrate_does_not_affect_other_skills():
    """bonus2 bDelayrate on one skill must not reduce a different skill's ACD."""
    gb = GearBonuses(skill_delayrate={"MG_SOULSTRIKE": -10})
    _, delay = calculate_skill_timing(
        "MG_NAPALMBEAT", 5, _skill_data(acd=1000, levels=10), _DEFAULT_STATUS, gb, {}
    )
    assert delay == 1000


def test_per_skill_delayrate_stacks_additively_with_global():
    """Global bDelayrate and per-skill bDelayrate add before the single multiply."""
    gb = GearBonuses(delayrate=-15, skill_delayrate={"MG_SOULSTRIKE": -10})
    _, delay = calculate_skill_timing(
        "MG_SOULSTRIKE", 5, _skill_data(acd=1000, levels=10), _DEFAULT_STATUS, gb, {}
    )
    # (100 + (-15) + (-10)) / 100 * 1000 = 750
    assert delay == 750


# ---------------------------------------------------------------------------
# calculate_skill_timing — PS per-skill cooldowns not in effective_delay
# ---------------------------------------------------------------------------

def test_as_splasher_effective_delay_is_not_3000():
    """AS_SPLASHER: effective_delay from calculate_skill_timing is the ACD floor (100ms),
    NOT the 3s per-skill cooldown. The cooldown is a period floor applied later."""
    skill_data = loader.get_skill(141)  # AS_SPLASHER id=141
    assert skill_data is not None
    _, delay = calculate_skill_timing(
        "AS_SPLASHER", 1, skill_data, _DEFAULT_STATUS, _DEFAULT_GB, {},
        server="payon_stories",
    )
    assert delay == 100  # min_skill_delay_limit; NOT 3000


def test_kn_chargeatk_zero_cast_in_ps():
    """KN_CHARGEATK: effective_cast is 0 in PS (ps_zero_cast override)."""
    skill_data = loader.get_skill(1001)  # KN_CHARGEATK id=1001
    assert skill_data is not None
    cast, _ = calculate_skill_timing(
        "KN_CHARGEATK", 1, skill_data, _DEFAULT_STATUS, _DEFAULT_GB, {},
        server="payon_stories",
    )
    assert cast == 0


# ---------------------------------------------------------------------------
# _skill_period_ms — formula cases
# ---------------------------------------------------------------------------

def test_period_vanilla_cd_dominates():
    """vanilla_cd > cast+ACD and > adelay → period = vanilla_cd."""
    period = _skill_period_ms(0, 500, _skill_data(cooldown=3000), 1, 0, 1000.0)
    assert period == 3000.0


def test_period_ps_min_period_dominates():
    """ps_min_period > all other floors → period = ps_min_period."""
    period = _skill_period_ms(0, 100, _skill_data(cooldown=0), 1, 4000, 2000.0)
    assert period == 4000.0


def test_period_adelay_floor_dominates():
    """amotion dominates when cast+ACD and cooldowns are all smaller."""
    period = _skill_period_ms(0, 300, _skill_data(cooldown=0), 1, 0, 2000.0)
    assert period == 2000.0


def test_period_cast_plus_acd_dominates():
    """cast+ACD dominates when it exceeds all other floors."""
    period = _skill_period_ms(2000, 1500, _skill_data(cooldown=0), 1, 0, 500.0)
    assert period == 3500.0


def test_bragi_reduces_acd_but_not_cooldown_floor():
    """Bragi reduces effective_delay (via status.after_cast_delay_reduction_pct) but
    cannot reduce the cooldown floor because _skill_period_ms is called with the
    already-reduced delay — the ps_min_period floor remains unchanged.

    This is the critical architectural invariant: per-skill cooldowns are immune to
    Bragi/delayrate because they are applied after skill_timing, not inside it.
    """
    skill_data = _skill_data(acd=2000, cooldown=0, levels=10)
    ps_min = 3000

    # No Bragi: delay=2000 → period = max(2000, 3000, 1000) = 3000
    status_no_bragi = StatusData(dex=50, agi=50, aspd=150.0, after_cast_delay_reduction_pct=0)
    _, delay_no_bragi = calculate_skill_timing("SOME_SKILL", 1, skill_data, status_no_bragi, _DEFAULT_GB, {})
    period_no_bragi = _skill_period_ms(0, delay_no_bragi, skill_data, 1, ps_min, 1000.0)

    # 50% Bragi: delay≈1000 → period = max(1000, 3000, 1000) = 3000 — same result
    status_bragi = StatusData(dex=50, agi=50, aspd=150.0, after_cast_delay_reduction_pct=50)
    _, delay_bragi = calculate_skill_timing("SOME_SKILL", 1, skill_data, status_bragi, _DEFAULT_GB, {})
    period_bragi = _skill_period_ms(0, delay_bragi, skill_data, 1, ps_min, 1000.0)

    assert delay_bragi < delay_no_bragi, "Bragi must reduce effective_delay"
    assert period_bragi == period_no_bragi == 3000.0, "Cooldown floor must be immune to Bragi"


# ---------------------------------------------------------------------------
# BattlePipeline integration — default build + mob 1002
# ---------------------------------------------------------------------------

def test_pipeline_default_build_mob_1002():
    """Smoke test: BattlePipeline runs without error on a default build targeting mob 1002.

    Asserts only structural invariants (no crash, non-negative damage and period)
    rather than exact values, since the default build has no weapon or stats.
    """
    config  = BattleConfig()
    build   = PlayerBuild(target_mob_id=1002, server="payon_stories")
    gb, eff_build, weapon, status = resolve_player_state(build, config)
    target  = loader.get_monster(1002)

    skill = SkillInstance(id=5, level=1)  # SM_BASH lv 1 — simple physical skill
    result = BattlePipeline(config).calculate(status, weapon, skill, target, eff_build, gb)

    assert result.period_ms > 0.0
    assert result.normal.avg_damage >= 0.0
