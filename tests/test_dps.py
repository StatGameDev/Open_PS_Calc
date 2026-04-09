"""Unit tests for core/calculators/dps_calculator.py and AttackDefinition.

Run with:  python -m pytest tests/test_dps.py   (from project root)
"""
import pytest
from core.models.attack_definition import AttackDefinition
from core.calculators.dps_calculator import calculate_dps, FormulaSelectionStrategy

_STRATEGY = FormulaSelectionStrategy()


def test_single_attack_type():
    """Basic: one outcome type, always-hit, always normal — dps = damage / delay * 1000."""
    attacks = [AttackDefinition(avg_damage=100.0, pre_delay=0.0, post_delay=500.0, chance=1.0)]
    result = calculate_dps(attacks, _STRATEGY)
    assert result == pytest.approx(100.0 / 500.0 * 1000, rel=1e-9)


def test_with_crit_effective_crit_scaling():
    """With crit: expected DPS = (normal_weight*normal_dmg + crit_weight*crit_dmg) /
    (same_delay) * 1000, since both outcomes share the same adelay."""
    # 10% (effective) crit chance, 90% normal — all hits, same delay 400 ms
    delay = 400.0
    normal_dmg = 100.0
    crit_dmg   = 150.0
    attacks = [
        AttackDefinition(normal_dmg, 0.0, delay, 0.90),
        AttackDefinition(crit_dmg,   0.0, delay, 0.10),
    ]
    expected_dps = (0.90 * normal_dmg + 0.10 * crit_dmg) / delay * 1000.0
    assert calculate_dps(attacks, _STRATEGY) == pytest.approx(expected_dps, rel=1e-9)


def test_unequal_delay_edge_case():
    """Guard against the incorrect Σ(chance_i × dps_i) formula.

    When two attack types have different total delays, the correct formula
    Σ(chance_i × damage_i) / Σ(chance_i × delay_i)
    differs from the incorrect Σ(chance_i × (damage_i / delay_i)).

    This test verifies the difference explicitly so any regression will be caught.
    """
    # Attack A: 50% chance, 100 dmg, 200 ms delay  → dps_A = 500
    # Attack B: 50% chance, 200 dmg, 800 ms delay  → dps_B = 250
    attacks = [
        AttackDefinition(100.0, 0.0, 200.0, 0.5),
        AttackDefinition(200.0, 0.0, 800.0, 0.5),
    ]

    # Correct:   (0.5*100 + 0.5*200) / (0.5*200 + 0.5*800) * 1000
    #          = 150 / 500 * 1000 = 300
    correct = (0.5 * 100.0 + 0.5 * 200.0) / (0.5 * 200.0 + 0.5 * 800.0) * 1000.0

    # Incorrect: 0.5 * (100/200)*1000 + 0.5 * (200/800)*1000
    #          = 0.5*500 + 0.5*250 = 375
    incorrect = 0.5 * (100.0 / 200.0 * 1000.0) + 0.5 * (200.0 / 800.0 * 1000.0)

    result = calculate_dps(attacks, _STRATEGY)

    assert result == pytest.approx(correct, rel=1e-9)
    assert result != pytest.approx(incorrect, rel=1e-3), (
        "calculate_dps is using the incorrect Σ(chance_i × dps_i) formula"
    )
