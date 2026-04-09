"""Tests for card-source attribution in GearBonuses.

Covers:
  1. ItemEffect source tagging (source_slot, source_item_id)
  2. GearBonusAggregator.from_cards sub-aggregate — card slots vs equipment slots
  3. SC_CONCENTRATION formula correctly excludes card-bonus AGI/DEX from the
     amplification base (Hercules: agi += (agi - val3) * val2 / 100, val3=param_bonus[1])

Fixtures:
  Kukre_Card  (4027) — bonus bAgi,2                     (card)
  Drops_Card  (4004) — bonus bDex,1; bonus bHit,3       (card)
  Sahkkat     (2280) — bonus bAgi,1                     (armor — equipment slot)

Run with:  python -m pytest tests/test_g245_card_source.py  (from project root)
"""
import pytest
from core.config import BattleConfig
from core.gear_bonus_aggregator import GearBonusAggregator
from core.calculators.status_calculator import StatusCalculator
from core.models.build import PlayerBuild
from core.models.gear_bonuses import GearBonuses
from core.models.weapon import Weapon

# ── item IDs used as fixtures ──────────────────────────────────────────────────
_KUKRE_CARD  = 4027   # bonus bAgi,2
_DROPS_CARD  = 4004   # bonus bDex,1; bonus bHit,3
_SAHKKAT     = 2280   # bonus bAgi,1  (armor, not a card)

# ── helpers ───────────────────────────────────────────────────────────────────

def _compute(equipped: dict) -> GearBonuses:
    """Thin wrapper: compute GearBonuses with no refine/script context."""
    return GearBonusAggregator.compute(equipped)


def _sc_concentration_status(
    base_agi: int,
    bonus_agi: int,
    card_agi: int,
    sc_lv: int,
    base_dex: int = 1,
    bonus_dex: int = 0,
    card_dex: int = 0,
) -> tuple[int, int]:
    """Return (status_agi, status_dex) after SC_CONCENTRATION is applied.

    bonus_agi / bonus_dex represent the total gear bonus already folded into
    PlayerBuild.bonus_* by build_applicator (card + equip combined), matching
    the real pipeline. card_agi / card_dex seed gb.from_cards for the exclusion.
    """
    gb = GearBonuses(agi=bonus_agi, dex=bonus_dex)
    gb.from_cards = GearBonuses(agi=card_agi, dex=card_dex)

    build = PlayerBuild(
        base_agi=base_agi,
        bonus_agi=bonus_agi,
        base_dex=base_dex,
        bonus_dex=bonus_dex,
        active_status_levels={"SC_CONCENTRATION": sc_lv},
    )
    st = StatusCalculator(BattleConfig()).calculate(build, Weapon(), gb)
    return st.agi, st.dex


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ItemEffect source tagging
# ═══════════════════════════════════════════════════════════════════════════════

def test_effects_tagged_with_source_slot():
    """Effects from a card slot carry source_slot = the slot name."""
    gb = _compute({"armor_card": _KUKRE_CARD})
    assert gb.all_effects, "Expected at least one effect from Kukre_Card"
    for eff in gb.all_effects:
        assert eff.source_slot == "armor_card", (
            f"Expected source_slot='armor_card', got {eff.source_slot!r}"
        )


def test_effects_tagged_with_source_item_id():
    """Effects from a card carry source_item_id = the item's DB id."""
    gb = _compute({"armor_card": _KUKRE_CARD})
    for eff in gb.all_effects:
        assert eff.source_item_id == _KUKRE_CARD, (
            f"Expected source_item_id={_KUKRE_CARD}, got {eff.source_item_id}"
        )


def test_equipment_effects_also_tagged():
    """Non-card equipment effects are also tagged with their slot and item ID."""
    gb = _compute({"armor": _SAHKKAT})
    assert gb.all_effects
    for eff in gb.all_effects:
        assert eff.source_slot == "armor"
        assert eff.source_item_id == _SAHKKAT


def test_multiple_slots_tagged_independently():
    """Effects from two different slots carry distinct source_slot values."""
    gb = _compute({"armor": _SAHKKAT, "armor_card": _KUKRE_CARD})
    slots_seen = {eff.source_slot for eff in gb.all_effects}
    assert "armor" in slots_seen
    assert "armor_card" in slots_seen


# ═══════════════════════════════════════════════════════════════════════════════
# 2. from_cards sub-aggregate
# ═══════════════════════════════════════════════════════════════════════════════

def test_from_cards_always_present():
    """from_cards is never None after compute(), even with no cards equipped."""
    gb = _compute({})
    assert gb.from_cards is not None


def test_from_cards_card_agi_accumulated():
    """Card-slot AGI bonus lands in from_cards.agi."""
    gb = _compute({"armor_card": _KUKRE_CARD})   # +2 AGI
    assert gb.from_cards.agi == 2


def test_from_cards_card_dex_accumulated():
    """Card-slot DEX bonus lands in from_cards.dex."""
    gb = _compute({"armor_card": _DROPS_CARD})   # +1 DEX
    assert gb.from_cards.dex == 1


def test_from_cards_card_non_stat_field():
    """Non-stat card bonuses (HIT) also land in from_cards."""
    gb = _compute({"armor_card": _DROPS_CARD})   # bonus bHit,3
    assert gb.from_cards.hit == 3


def test_from_cards_equip_slot_excluded():
    """Equipment-slot bonuses do NOT appear in from_cards."""
    gb = _compute({"armor": _SAHKKAT})   # +1 AGI from armor
    assert gb.from_cards.agi == 0


def test_from_cards_partial_split():
    """With card +2 AGI and equipment +1 AGI: total=3, from_cards=2."""
    gb = _compute({"armor": _SAHKKAT, "armor_card": _KUKRE_CARD})
    assert gb.agi == 3,             f"Expected total agi=3, got {gb.agi}"
    assert gb.from_cards.agi == 2,  f"Expected card agi=2, got {gb.from_cards.agi}"


def test_from_cards_multiple_card_slots():
    """Bonuses from two separate card slots both accumulate in from_cards."""
    gb = _compute({"armor_card": _KUKRE_CARD, "right_hand_card_1": _DROPS_CARD})
    assert gb.from_cards.agi == 2   # Kukre +2 AGI
    assert gb.from_cards.dex == 1   # Drops +1 DEX


def test_from_cards_no_nested_from_cards():
    """from_cards.from_cards is None — no double-nesting."""
    gb = _compute({"armor_card": _KUKRE_CARD})
    assert gb.from_cards.from_cards is None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SC_CONCENTRATION formula
# ═══════════════════════════════════════════════════════════════════════════════

def test_sc_concentration_excludes_card_agi():
    """Card AGI is excluded from SC_CONCENTRATION amplification base.

    Scenario: base_agi=100, equip_agi=40, card_agi=50 → status.agi=190 before SC.
    SC_CONCENTRATION lv10: val2=12.
    Hercules: agi += (190 - 50) * 12 // 100 = 140 * 12 // 100 = 16  → 206
    Wrong:    agi += 190 * 12 // 100 = 22  → 212
    """
    agi, _ = _sc_concentration_status(
        base_agi=100, bonus_agi=90, card_agi=50, sc_lv=10
    )
    # status.agi before SC = 100 + 90 = 190
    # Correct: 190 + (190 - 50) * 12 // 100 = 190 + 16 = 206
    assert agi == 206, f"Expected 206, got {agi}"


def test_sc_concentration_excludes_card_dex():
    """Card DEX is excluded from SC_CONCENTRATION amplification base."""
    _, dex = _sc_concentration_status(
        base_agi=1, bonus_agi=0, card_agi=0,
        base_dex=80, bonus_dex=30, card_dex=20,
        sc_lv=10,
    )
    # status.dex before SC = 80 + 30 = 110
    # Correct: 110 + (110 - 20) * 12 // 100 = 110 + 90 * 12 // 100 = 110 + 10 = 120
    assert dex == 120, f"Expected 120, got {dex}"


def test_sc_concentration_zero_card_agi_unchanged():
    """With no card AGI, SC_CONCENTRATION amplifies the full stat (old behaviour preserved)."""
    agi, _ = _sc_concentration_status(
        base_agi=100, bonus_agi=50, card_agi=0, sc_lv=10
    )
    # status.agi = 150; val2=12
    # (150 - 0) * 12 // 100 = 18  → 168
    assert agi == 150 + 150 * 12 // 100


def test_sc_concentration_all_card_agi_no_amplification():
    """If ALL AGI comes from cards, SC_CONCENTRATION adds 0 amplification."""
    # base_agi=0, bonus_agi=50 (all from cards), card_agi=50
    # status.agi = 50; SC lv10
    # (50 - 50) * 12 // 100 = 0
    agi, _ = _sc_concentration_status(
        base_agi=0, bonus_agi=50, card_agi=50, sc_lv=10
    )
    assert agi == 50


def test_sc_concentration_lv1():
    """SC_CONCENTRATION lv1 (val2=3) with mixed card/equip AGI."""
    agi, _ = _sc_concentration_status(
        base_agi=100, bonus_agi=20, card_agi=10, sc_lv=1
    )
    # status.agi = 120; val2=3
    # (120 - 10) * 3 // 100 = 110 * 3 // 100 = 3
    assert agi == 120 + 3
