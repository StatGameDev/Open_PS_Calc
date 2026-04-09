"""
ItemEffect — dataclass representing one parsed bonus from an item script.

Produced by ItemScriptParser (item_script_parser.py).
Consumed by GearBonusAggregator (gear_bonus_aggregator.py) to accumulate GearBonuses.
description is generated from BonusDef templates in bonus_definitions.py.
"""
from dataclasses import dataclass, field


@dataclass
class ItemEffect:
    """One parsed effect from an item script."""
    bonus_type: str       # e.g. "bStr", "bSubClass", "bAutoSpell"
    arity: int            # 1 = bonus, 2 = bonus2, 3 = bonus3
    params: list          # e.g. [3] or ["RC_Boss", 40]
    description: str = ""  # human-readable, generated from template or manual override
    source_slot: str | None = None      # slot this effect came from, e.g. "armor_card", "right_hand"
    source_item_id: int | None = None   # item ID for tooltip attribution
