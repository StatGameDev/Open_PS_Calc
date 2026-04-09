"""Tests for bAddAtkEle (G219) and bHolyStrikeChance (G243).

bAddAtkEle  — bonus2 bAddAtkEle,Ele_X,N: outgoing attack-element damage bonus.
              Applied in CardFix as a multiplicative step keyed on eff_atk_ele,
              not on the target's element.

bHolyStrikeChance — bonus bHolyStrikeChance,N: combo Holy Strike proc chance.
                    Populated via ps_item_combo_db (Ancient_Mummy_Card + Mummy_Card)
                    and accumulated into GearBonuses.holy_strike_bonus_chance.

Run with:  python -m pytest tests/test_bAddAtkEle_bHolyStrikeChance.py
"""
import pytest
from core.models.build import PlayerBuild
from core.models.gear_bonuses import GearBonuses
from core.models.target import Target
from core.models.damage import DamageResult
from core.calculators.modifiers.card_fix import CardFix
from core.gear_bonus_aggregator import GearBonusAggregator
from core.server_profiles import PAYON_STORIES
from pmf.operations import _uniform_pmf, pmf_stats

# ── item IDs ──────────────────────────────────────────────────────────────────
_ANCIENT_MUMMY_CARD = 4248   # bonus3 bAutoSpellWhenHit,AL_CRUCIS,5,30;
_MUMMY_CARD         = 4106   # bonus bHit,20;  — combo partner

# ── shared fixtures ───────────────────────────────────────────────────────────

def _flat_pmf(value: int) -> dict:
    return _uniform_pmf(value, value)


def _mob_target(element: int = 0) -> Target:
    """Minimal mob target: Neutral element, Medium, Formless, non-boss."""
    return Target(
        def_=0, vit=0, size="Medium", race="Formless",
        element=element, element_level=1, is_boss=False,
        level=1, luk=0, agi=0,
    )


def _pc_target(sub_ele: dict | None = None) -> Target:
    """Minimal player target for PvP sub_ele checks."""
    return Target(
        def_=0, vit=0, size="Medium", race="Demi-Human",
        element=6, element_level=1, is_boss=False,
        level=1, luk=0, agi=0,
        is_pc=True,
        sub_ele=sub_ele or {},
    )


def _empty_build() -> PlayerBuild:
    return PlayerBuild()


def _run_card_fix(
    gear_bonuses: GearBonuses,
    atk_element: int,
    target: Target,
    is_ranged: bool = False,
    damage: int = 1000,
) -> int:
    """Run CardFix.calculate and return the average output damage."""
    pmf = _flat_pmf(damage)
    result = DamageResult()
    pmf = CardFix.calculate(_empty_build(), gear_bonuses, atk_element, target, is_ranged, pmf, result)
    _, _, av = pmf_stats(pmf)
    return round(av)


# ═══════════════════════════════════════════════════════════════════════════════
# bAddAtkEle — attacker-side bonus keyed on outgoing attack element
# ═══════════════════════════════════════════════════════════════════════════════

def test_add_atk_ele_fires_on_matching_element():
    """bAddAtkEle,Ele_Poison,10 adds 10% when atk_element is Poison (5)."""
    gb = GearBonuses(add_atk_ele={"Ele_Poison": 10})
    out = _run_card_fix(gb, atk_element=5, target=_mob_target(), damage=1000)
    assert out == 1100


def test_add_atk_ele_no_bonus_on_wrong_element():
    """bAddAtkEle,Ele_Poison,10 has no effect when atk_element is Neutral (0)."""
    gb = GearBonuses(add_atk_ele={"Ele_Poison": 10})
    out = _run_card_fix(gb, atk_element=0, target=_mob_target(), damage=1000)
    assert out == 1000


def test_add_atk_ele_independent_of_target_element():
    """bAddAtkEle fires based on attack element regardless of target's element.

    Poison attack (5) vs Fire-element target (3): bonus applies.
    Confirms add_atk_ele is not confused with bAddEle (target-element check).
    """
    gb = GearBonuses(add_atk_ele={"Ele_Poison": 10})
    out = _run_card_fix(gb, atk_element=5, target=_mob_target(element=3), damage=1000)
    assert out == 1100


def test_add_atk_ele_stacks_with_add_ele():
    """bAddAtkEle and bAddEle (target element) stack as separate multiplicative steps."""
    # Poison attack vs Poison-element target: both bonuses should apply.
    gb = GearBonuses(
        add_atk_ele={"Ele_Poison": 10},
        add_ele={"Ele_Poison": 20},
    )
    out = _run_card_fix(gb, atk_element=5, target=_mob_target(element=5), damage=1000)
    # 1000 × 1.20 × 1.10 = 1320
    assert out == 1320


# ═══════════════════════════════════════════════════════════════════════════════
# PvP t_ele fix — target-side sub_ele uses resolved atk_element, not weapon.element
# ═══════════════════════════════════════════════════════════════════════════════

def test_pvp_sub_ele_uses_atk_element():
    """Target-side sub_ele reduction is keyed on atk_element (endow-resolved), not raw weapon element.

    This was the latent bug: CardFix previously read weapon.element directly,
    bypassing endow/skill-element resolution already done by the pipeline.
    With atk_element=Fire (3) passed in, Ele_Fire sub_ele must apply.
    """
    target = _pc_target(sub_ele={"Ele_Fire": 25})
    gb = GearBonuses()
    out = _run_card_fix(gb, atk_element=3, target=target, damage=1000)
    # 1000 × (100-25)/100 = 750
    assert out == 750


def test_pvp_sub_ele_neutral_atk_element_uses_neutral_reduction():
    """With atk_element=0 (Neutral), Ele_Neutral sub_ele applies, Ele_Fire does not."""
    target = _pc_target(sub_ele={"Ele_Neutral": 10, "Ele_Fire": 50})
    gb = GearBonuses()
    out = _run_card_fix(gb, atk_element=0, target=target, damage=1000)
    # Only Neutral reduction: 1000 × 90/100 = 900
    assert out == 900


# ═══════════════════════════════════════════════════════════════════════════════
# bHolyStrikeChance — combo populates GearBonuses.holy_strike_bonus_chance
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_with_combos(equipped: dict) -> GearBonuses:
    """compute() + apply_combo_bonuses() with PS profile — mirrors player_state_builder."""
    gb = GearBonusAggregator.compute(equipped)
    GearBonusAggregator.apply_combo_bonuses(gb, equipped, profile=PAYON_STORIES)
    return gb


def test_holy_strike_chance_zero_without_combo():
    """With only Ancient Mummy Card (no Mummy Card), holy_strike_bonus_chance is 0."""
    gb = _compute_with_combos({"armor_card": _ANCIENT_MUMMY_CARD})
    assert gb.holy_strike_bonus_chance == 0


def test_holy_strike_chance_populated_by_combo():
    """Ancient_Mummy_Card + Mummy_Card combo sets holy_strike_bonus_chance = 5."""
    gb = _compute_with_combos({
        "armor_card":        _ANCIENT_MUMMY_CARD,
        "right_hand_card_1": _MUMMY_CARD,
    })
    assert gb.holy_strike_bonus_chance == 5
