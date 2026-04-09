"""
BuffsSection — self buffs, party buffs, songs/dances, ensembles, and misc effects.

Eight CollapsibleSubGroups: Self Buffs, Party Buffs, Songs & Dances, Ensembles,
Guild Buffs, Miscellaneous Effects. Self-buff visibility is job-filtered via
update_job(); server-mode visibility controlled via set_server().
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from core.data.pets import PET_BONUSES, pet_bonus_summary
from core.data_loader import loader
from core.models.build import PlayerBuild
from core.server_profiles import get_profile
from gui.section import Section
from gui.widgets import LevelWidget, NoWheelCombo, NoWheelSpin
from gui.widgets.collapsible_sub_group import CollapsibleSubGroup

# PS Clan dropdown items: (build.clan key, display label)
_CLAN_ITEMS: list[tuple[str, str]] = [
    ("",                "None"),
    ("sword_clan",      "Sword Clan  STR+1 VIT+1"),
    ("arch_wand_clan",  "Arch Wand Clan  INT+1 DEX+1"),
    ("golden_mace_clan","Golden Mace Clan  INT+1 VIT+1"),
    ("crossbow_clan",   "Crossbow Clan  DEX+1 AGI+1"),
    ("artisan_clan",    "Artisan Clan  DEX+1 LUK+1"),
    ("vile_wind_clan",  "Vile Wind Clan  STR+1 AGI+1"),
]

# Pet dropdown items: (pet_name key, display label with summary)
_PET_ITEMS: list[tuple[str, str]] = [("", "— None —")] + [
    (name, name + ("  " + pet_bonus_summary(PET_BONUSES[name]) if PET_BONUSES[name] else ""))
    for name in sorted(PET_BONUSES)
]

# Bard job IDs: Bard (19), Clown (4020)
_BARD_JOBS   = frozenset({19, 4020})
# Dancer job IDs: Dancer (20), Gypsy (4021)
_DANCER_JOBS = frozenset({20, 4021})
# PS-only self-buff SC keys: hidden in standard mode regardless of Show All.
_PS_ONLY_SC_KEYS: frozenset[str] = frozenset({"SC_DOUBLECASTING", "SC_COMBOFINISH_BUFF"})
# Vanilla-only self-buff SC keys: hidden in PS mode regardless of Show All.
# G108: SC_GS_ACCURACY (Increase Accuracy) was removed in PS; its bonus was folded into GS_SINGLEACTION.
_VANILLA_ONLY_SC_KEYS: frozenset[str] = frozenset({"SC_GS_ACCURACY"})
# Job restriction for PS-only buffs: Sage (16) + Professor/Scholar (4017)
_PS_SC_JOB_RESTRICTION: dict[str, frozenset[int]] = {
    "SC_DOUBLECASTING":    frozenset({16, 4017}),
    "SC_COMBOFINISH_BUFF": frozenset({15, 4016}),  # Monk + Champion
}

# ── Self Buffs ────────────────────────────────────────────────────────────────
# (sc_key, source_skill, has_level, min_lv, max_lv)
# Display names are resolved via loader.get_skill_display_name(source_skill, profile).
# Exceptions use _SELF_BUFF_CUSTOM_LABELS: widgets tracking quantities or compound concepts
# whose label intentionally differs from the source skill's display name.
# All are job-filtered via update_job(). Show All overrides filtering.
# SC_ADRENALINE and SC_ASSNCROS are in support_buffs / song_state — not here.
_SELF_BUFFS: list[tuple] = [
    ("SC_AURABLADE",          "LK_AURABLADE",        True,  1,  5),
    ("SC_MAXIMIZEPOWER",      "BS_MAXIMIZE",          False, 1,  1),
    ("SC_OVERTHRUST",         "BS_OVERTHRUST",        True,  1,  5),
    ("SC_OVERTHRUSTMAX",      "WS_OVERTHRUSTMAX",     True,  1,  5),
    # SC_WEAPONPERFECT: flag&8 in calc_base_damage2 bypasses SizeFix (battle.c:497,663)
    ("SC_WEAPONPERFECT",      "BS_WEAPONPERFECT",     False, 1,  1),
    ("SC_TWOHANDQUICKEN",     "KN_TWOHANDQUICKEN",    False, 1,  1),
    ("SC_SPEARQUICKEN",       "CR_SPEARQUICKEN",      True,  1,  10),
    ("SC_ONEHANDQUICKEN",     "KN_ONEHAND",           False, 1,  1),
    # ── Swordman / Knight / Crusader ──────────────────────────────────────────
    # SC_SUB_WEAPONPROPERTY: stub; fire property + 20% dmg for one hit (battle.c:996-1001)
    ("SC_SUB_WEAPONPROPERTY", "SM_MAGNUM",            False, 1,  1),
    # SC_AUTOBERSERK: stub; auto-applies SC_PROVOKE when HP<25% — no outgoing dmg formula
    ("SC_AUTOBERSERK",        "SM_AUTOBERSERK",       False, 1,  1),
    # SC_ENDURE: mdef += val1=lv — status_calculator.py (status.c:5149)
    ("SC_ENDURE",             "SM_ENDURE",            True,  1,  10),
    # SC_AUTOGUARD: stub; block chance incoming — no outgoing effect
    ("SC_AUTOGUARD",          "CR_AUTOGUARD",         False, 1,  1),
    # SC_REFLECTSHIELD: stub; reflect incoming melee — advanced/incoming only
    ("SC_REFLECTSHIELD",      "CR_REFLECTSHIELD",     False, 1,  1),
    # SC_DEFENDER: aspd_rate += val4=250-50×lv — status_calculator.py (status_calc_aspd_rate:5674)
    ("SC_DEFENDER",           "CR_DEFENDER",          True,  1,  5),
    # ── Monk / Champion ───────────────────────────────────────────────────────
    # MO_SPIRITBALL: no SC; sphere count stored as active_status_levels entry.
    # Custom label "Spirit Spheres" — tracks sphere quantity, not the casting skill.
    ("MO_SPIRITBALL",         "MO_CALLSPIRITS",       True,  1,  5),
    # SC_STEELBODY: aspd_rate += 250; def cap=90 stub — status_calculator.py
    ("SC_STEELBODY",          "MO_STEELBODY",         False, 1,  1),
    # SC_COMBOFINISH_BUFF: PS +15% damage for 8s after MO_COMBOFINISH (JSONL id=273).
    # Custom label keeps asterisk (*) marking PS-only nature.
    ("SC_COMBOFINISH_BUFF",   "MO_COMBOFINISH",       False, 1,  1),
    # SC_EXPLOSIONSPIRITS: cri += val2=75+25×lv — status_calculator.py (status.c:4753)
    ("SC_EXPLOSIONSPIRITS",   "MO_EXPLOSIONSPIRITS",  True,  1,  10),
    # ── Archer / Hunter ───────────────────────────────────────────────────────
    # SC_CONCENTRATION: agi/dex += stat * (2+lv)% — status_calculator.py (status.c:4007, 4195)
    ("SC_CONCENTRATION",      "AC_CONCENTRATION",     True,  1,  10),
    # ── Merchant ──────────────────────────────────────────────────────────────
    # SC_SHOUT: str += 4 flat — status_calculator.py (status.c:3956)
    ("SC_SHOUT",              "MC_LOUD",              False, 1,  1),
    # ── Mage / Sage ───────────────────────────────────────────────────────────
    # SC_ENERGYCOAT: SP% interval stored as val 1–5 (per=val-1); reduction=6*(1+per)%
    # battle.c:3373-3379 (#else not RENEWAL): per=(100*sp/max_sp-1)/20; dmg-=dmg*(6*(1+per))/100
    ("SC_ENERGYCOAT",         "MG_ENERGYCOAT",        True,  1,  5),
    # ── Assassin / Assassin Cross ─────────────────────────────────────────────
    # SC_CLOAKING: PS ×2 first auto-attack; AS_SONICBLOW ×1.1 — battle_pipeline.py
    ("SC_CLOAKING",           "AS_CLOAKING",          False, 1,  1),
    # SC_POISONREACT: stub; counter attack — no direct outgoing stat
    ("SC_POISONREACT",        "AS_POISONREACT",       False, 1,  1),
    # ── Rogue / Stalker ───────────────────────────────────────────────────────
    # SC_RG_CCONFINE_M: flee += 10 — status_calculator.py (status.c:4874)
    ("SC_RG_CCONFINE_M",      "RG_CLOSECONFINE",      False, 1,  1),
    # ── Gunslinger ────────────────────────────────────────────────────────────
    # GS_COINS: no SC; coin count stored as active_status_levels entry.
    # Custom label "Coins" — tracks coin quantity, not the casting skill.
    ("GS_COINS",              "GS_GLITTERING",        True,  1,  10),
    # SC_GS_MADNESSCANCEL / SC_GS_ADJUSTMENT are mutually exclusive — rendered as a
    # single "GS Stance" combo. Sentinel key "_GS_STANCE" handled specially in build/collect/update.
    # Custom label "GS Stance" — compound widget spanning two skills.
    # source_skill = "GS_MADNESSCANCEL" so job filter shows it for GS jobs (GS_ADJUSTMENT co-occurs).
    ("_GS_STANCE",            "GS_MADNESSCANCEL",     False, 1,  1),
    # SC_GS_ACCURACY: agi+4, dex+4, hit+20 — status_calculator.py (status.c:4023, 4219, 4811)
    ("SC_GS_ACCURACY",        "GS_INCREASING",        False, 1,  1),
    # SC_GS_GATLINGFEVER: batk+=20+10×lv; flee-=5×lv; aspd in max pool — status_calculator.py
    ("SC_GS_GATLINGFEVER",    "GS_GATLINGFEVER",      True,  1,  10),
    # ── Ninja ─────────────────────────────────────────────────────────────────
    # SC_NJ_NEN: str+=lv; int_+=lv — status_calculator.py (status.c:3962, 4148)
    ("SC_NJ_NEN",             "NJ_NEN",               True,  1,  10),
    # ── Taekwon ───────────────────────────────────────────────────────────────
    # SC_RUN: stub; movement speed +55 (status.c:5375); FLEE effect unconfirmed
    ("SC_RUN",                "TK_RUN",               False, 1,  1),
    # ── Endow — Assassin ─────────────────────────────────────────────────────
    # SC_ENCHANTPOISON: weapon element → Poison (8); job-filtered via AS_ENCHANTPOISON
    ("SC_ENCHANTPOISON",      "AS_ENCHANTPOISON",     False, 1,  1),
    # ── PS-only — Sage / Scholar ──────────────────────────────────────────────
    # SC_DOUBLECASTING: PS-only toggle; 100% chance to double-cast bolt skills.
    # Added to Sage skill tree on PS (no pre-reqs, max lv1). Duration 300s.
    # Affects: MG_COLDBOLT/FIREBOLT/LIGHTNINGBOLT (vanilla), MG_SOULSTRIKE, WZ_EARTHSPIKE (PS-added).
    # Second cast fires via skill->addtimerskill at tick+dmg.amotion, same skill_lv, flag|2.
    # Hindsight (SA_AUTOSPELL) active: second cast uses ceil(skill_lv/2) level — handled in _calculate_autospell.
    # Source: skill.c:3936-3944, status.c:8495-8497
    ("SC_DOUBLECASTING",      "PF_DOUBLECASTING",     False, 1,  1),
    # SC_ADRENALINE self buff: Blacksmith/Whitesmith only (job-filtered via BS_ADRENALINE).
    # Stored in support_buffs["SC_ADRENALINE"] = 300 — NOT in active_status_levels.
    # Handled specially in collect_into / load_build (see "SC_ADRENALINE_SELF" guards).
    ("SC_ADRENALINE_SELF",    "BS_ADRENALINE",        False, 1,  1),
]

# Custom display labels for self-buff entries whose label deliberately differs from the
# source skill's display name (quantity trackers, compound widgets, PS-only markers).
_SELF_BUFF_CUSTOM_LABELS: dict[str, str] = {
    "MO_SPIRITBALL":       "Spirit Spheres",       # quantity widget, not "Call Spirits"
    "GS_COINS":            "Coins",                 # quantity widget, not "Coin Flip"
    "_GS_STANCE":          "GS Stance",             # compound: Madness Canceler + Adjustment
    "SC_COMBOFINISH_BUFF": "Combo Finish Buff*",    # PS-only; asterisk marks PS nature
}


def _resolve_self_buff_label(sc_key: str, source_skill: str, server: str) -> str:
    """Return the display label for a self-buff row.

    Checks _SELF_BUFF_CUSTOM_LABELS first; otherwise delegates to the skill name resolver.
    """
    if sc_key in _SELF_BUFF_CUSTOM_LABELS:
        return _SELF_BUFF_CUSTOM_LABELS[sc_key]
    return loader.get_skill_display_name(source_skill, get_profile(server))


# ── Party Buffs ───────────────────────────────────────────────────────────────
# Tuple layout:
#   (sc_key, display_name, widget_type, min_lv, max_lv)
#   widget_type: "spin" = QComboBox(Off, 1..max) — 0=off
#                "check" = QCheckBox only
#                "endow"  = NoWheelCombo; stores SC key string in support_buffs["weapon_endow_sc"]
_PARTY_BUFFS: list[tuple] = [
    ("SC_BLESSING",   "Blessing",        "spin",       0, 10),
    ("SC_INC_AGI",    "Increase AGI",    "spin",       0, 10),
    ("SC_GLORIA",     "Gloria",          "check",      0,  0),
    ("SC_ANGELUS",    "Angelus",         "spin",       0, 10),
    ("SC_IMPOSITIO",  "Impositio Manus", "spin",       0,  5),
    # SC_ADRENALINE party: received from a Blacksmith in the party (val3=200).
    # Self-cast by BS/WS is handled via SC_ADRENALINE_SELF in _SELF_BUFFS (val3=300).
    ("SC_ADRENALINE",  "Adrenaline Rush",       "check", 0,  0),
    # SC_ADRENALINE2: same val3=200 party formula; Whitesmith Spirit skill (external buff only).
    # status.c:5614-5616, 7232-7233
    ("SC_ADRENALINE2", "Adv. Adrenaline Rush",  "check", 0,  0),
    # SC_OVERTHRUST party: vanilla val3=5 fixed → checkbox (stores 1).
    # PS val3=5×level → spin (stores level 1-5); mechanic_flag BS_OVERTHRUST_PARTY_FULL_BONUS.
    # skill_ratio.py reads support_buffs["SC_OVERTHRUST"] when self buff not active.
    ("SC_OVERTHRUST",  "Overthrust (Party)",    "check_or_spin", 0, 5),
    # SC_SUFFRAGIUM: val2 = 15×lv % cast time reduction (status.c:8485; skill.c:17244)
    # Consumed on cast; treated as always active for the cast being calculated.
    ("SC_SUFFRAGIUM", "Suffragium",      "spin",       0,  3),
    # PR_ASPERSIO: weapon element → Holy (3); party cast (status.c:~5939)
    ("SC_ASPERSIO",   "Aspersio",        "check",      0,  0),
    # Sage endow: SA_FLAME/FROST/LIGHTNING/SEISMIC — weapon element override via "endow" combo
    # Stored as support_buffs["weapon_endow_sc"] = SC key string; PS config adds extra effects per SC
    ("weapon_endow_sc", "Sage Endow",    "endow",      0,  0),
]

# Sage endow combo options: (display_label, SC key stored in support_buffs["weapon_endow_sc"])
# Elements: Fire=4, Water=5, Wind=6, Earth=7 (status.c ~5931/5925/5934/5928)
_SAGE_ENDOW_OPTIONS: list[tuple[str, str | None]] = [
    ("— none —",                    None),
    ("SA_FLAMELAUNCHER — Fire",      "SC_PROPERTYFIRE"),
    ("SA_FROSTWEAPON — Water",       "SC_PROPERTYWATER"),
    ("SA_LIGHTNINGLOADER — Wind",    "SC_PROPERTYWIND"),
    ("SA_SEISMICWEAPON — Earth",     "SC_PROPERTYGROUND"),
]
# Ground effect SC key by combo index (index 0 = none)
_GROUND_SC_KEYS = [None, "SC_VOLCANO", "SC_DELUGE", "SC_VIOLENTGALE"]


# ── Bard Songs ────────────────────────────────────────────────────────────────
# (sc_key, source_skill, overrides: list of (stat_key, label))
# Display names resolved via loader.get_skill_display_name(source_skill, profile).
# stat_key maps to "SC_ASSNCROS_agi" in song_state; shared key is "caster_{stat}"
_BARD_SONGS: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("SC_ASSNCROS",  "BA_ASSASSINCROSS", [("agi", "AGI")]),
    ("SC_WHISTLE",   "BA_WHISTLE",       [("agi", "AGI"), ("luk", "LUK")]),
    ("SC_APPLEIDUN", "BA_APPLEIDUN",     [("vit", "VIT")]),
    ("SC_POEMBRAGI", "BA_POEMBRAGI",     [("dex", "DEX"), ("int", "INT")]),
]

# ── Dancer Dances ─────────────────────────────────────────────────────────────
# (sc_key, source_skill, overrides: list of (stat_key, label))
_DANCER_DANCES: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("SC_HUMMING",      "DC_HUMMING",       [("dex", "DEX")]),
    ("SC_FORTUNE",      "DC_FORTUNEKISS",   [("luk", "LUK")]),
    ("SC_SERVICEFORYU", "DC_SERVICEFORYOU", [("int", "INT")]),
]

# ── Ensembles ─────────────────────────────────────────────────────────────────
# (sc_key, source_skill, max_lv)
# Level only (0=off); no caster-stat formula.
_ENSEMBLES: list[tuple[str, str, int]] = [
    ("SC_DRUMBATTLE", "BD_DRUMBATTLEFIELD", 5),
    ("SC_NIBELUNGEN", "BD_RINGNIBELUNGEN",  5),
    ("SC_SIEGFRIED",  "BD_SIEGFRIED",       5),
]


def _stub_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("passive_sub_header")
    return lbl


class BuffsSection(Section):
    """Self buffs, party buffs, songs/dances, ensembles, and miscellaneous effects."""

    changed = Signal()
    # Emitted when a specific SC level changes — used by combat section to sync
    # mirrored param widgets (e.g. MO_SPIRITBALL → sphere count combo).
    sc_level_changed = Signal(str, int)  # (sc_key, new_value)

    def __init__(self, key, display_name, default_collapsed, compact_modes, parent=None):
        super().__init__(key, display_name, default_collapsed, compact_modes, parent)

        self._current_job_id: int = 0
        self._current_server: str = "standard"

        # Storage for Self Buffs
        self._sc_checks: dict[str, QCheckBox] = {}
        self._sc_combos: dict[str, LevelWidget] = {}      # level dropdowns (was _sc_spins)
        self._self_buff_widgets: dict[str, list[QWidget]] = {}

        # Storage for Party Buffs
        self._party_level_combos: dict[str, LevelWidget] = {}  # "spin" type (was _party_spins)
        self._party_checks: dict[str, QCheckBox] = {}
        self._party_combos: dict[str, NoWheelCombo] = {}  # SC_ADRENALINE only
        self._endow_combo: NoWheelCombo | None = None        # "endow" type (Sage)
        self._endow_lv1_check: QCheckBox | None = None       # PS-only: Lv1 side effect (SC_IMPOSITIO Lv5)
        self._ot_party_chk: QCheckBox | None = None          # check_or_spin: checkbox (vanilla)
        self._ot_party_spin: LevelWidget | None = None       # check_or_spin: spin (PS)

        # Storage for Songs & Dances (combined sub-group)
        self._song_level_combos: dict[str, LevelWidget] = {}   # SC_key → level combo (songs)
        self._dance_level_combos: dict[str, LevelWidget] = {}  # SC_key → level combo (dances)
        self._song_stat_spins: dict[str, dict[str, NoWheelSpin]] = {}  # SC_key → {stat → spin}
        self._song_lesson_combos: dict[str, LevelWidget] = {}  # SC_key → lesson combo

        # Storage for Ensembles
        self._ensemble_combos: dict[str, LevelWidget] = {}
        self._ensemble_labels: dict[str, QLabel] = {}

        # label stores for server-aware name refresh
        self._bard_song_labels: dict[str, QLabel] = {}
        self._dance_labels: dict[str, QLabel] = {}

        # Storage for Ground Effects
        self._ground_combo: NoWheelCombo | None = None
        self._ground_lv_combo: LevelWidget | None = None
        self._ground_note: QLabel | None = None

        # GS Stance combo (Barrage / Run and Gun mutual exclusivity)
        self._gs_stance_combo: NoWheelCombo | None = None

        # Pet dropdown
        self._combo_pet: NoWheelCombo | None = None

        # ── 1. Self Buffs ─────────────────────────────────────────────────
        self._sub_self = CollapsibleSubGroup("Self Buffs", default_collapsed=False)

        # "Show All" checkbox in sub-group header
        self._show_all_chk = QCheckBox("Show All")
        self._show_all_chk.setObjectName("passive_show_all")
        self._show_all_chk.toggled.connect(self._on_show_all_toggled)
        self._sub_self.add_header_widget(self._show_all_chk)

        buffs_widget = QWidget()
        buffs_grid = QGridLayout(buffs_widget)
        buffs_grid.setContentsMargins(0, 0, 0, 0)
        buffs_grid.setHorizontalSpacing(6)
        buffs_grid.setVerticalSpacing(3)
        buffs_grid.setColumnStretch(0, 1)  # label absorbs spare width; value widgets stay natural size

        for row_i, (sc_key, source_skill, has_lv, min_lv, max_lv) in enumerate(_SELF_BUFFS):
            if has_lv:
                # Combo-only: label in col 0, level dropdown (0=off) in col 1.
                lbl = QLabel(_resolve_self_buff_label(sc_key, source_skill, "standard"))
                buffs_grid.addWidget(lbl, row_i, 0)
                combo = LevelWidget(max_lv, include_off=True)
                if sc_key == "MO_SPIRITBALL":
                    combo.setItemText(0, "0")  # "0 spheres" reads more naturally than "Off"
                    combo.valueChanged.connect(
                        lambda v, k=sc_key: self.sc_level_changed.emit(k, v)
                    )
                elif sc_key == "SC_ENERGYCOAT":
                    # Relabel items: index 0 = inactive, 1–5 = SP% intervals
                    # battle.c:3373-3379: per=(100*sp/max_sp-1)/20; reduction=6*(1+per)%
                    for i, label in enumerate(
                        ["Current SP", "1–20%", "21–40%", "41–60%", "61–80%", "81–100%"]
                    ):
                        combo.setItemText(i, label)
                self._sc_combos[sc_key] = combo
                buffs_grid.addWidget(combo, row_i, 1)
                combo.valueChanged.connect(self._on_changed)
                self._self_buff_widgets[sc_key] = [lbl, combo]
            elif sc_key == "_GS_STANCE":
                # single combo replacing two mutually exclusive checkboxes.
                lbl = QLabel(_resolve_self_buff_label(sc_key, source_skill, "standard"))
                buffs_grid.addWidget(lbl, row_i, 0)
                combo = NoWheelCombo()
                combo.addItem("— (none)")
                combo.addItem(loader.get_skill_display_name("GS_MADNESSCANCEL"))  # index 1
                combo.addItem(loader.get_skill_display_name("GS_ADJUSTMENT"))     # index 2
                combo.currentIndexChanged.connect(self._on_changed)
                self._gs_stance_combo = combo
                buffs_grid.addWidget(combo, row_i, 1)
                self._self_buff_widgets[sc_key] = [lbl, combo]
            else:
                chk = QCheckBox(_resolve_self_buff_label(sc_key, source_skill, "standard"))
                chk.setObjectName("passive_sc_check")
                self._sc_checks[sc_key] = chk
                buffs_grid.addWidget(chk, row_i, 0)
                chk.toggled.connect(self._on_changed)
                self._self_buff_widgets[sc_key] = [chk]

        self._sub_self.add_content_widget(buffs_widget)
        self.add_content_widget(self._sub_self)

        # ── 2. Party Buffs ────────────────────────────────────────────────
        self._sub_party = CollapsibleSubGroup("Party Buffs", default_collapsed=False)

        party_widget = QWidget()
        party_grid = QGridLayout(party_widget)
        party_grid.setContentsMargins(0, 0, 0, 0)
        party_grid.setHorizontalSpacing(6)
        party_grid.setVerticalSpacing(3)
        party_grid.setColumnStretch(0, 1)  # label absorbs spare width; value widgets stay natural size

        for row_i, (sc_key, display, wtype, min_lv, max_lv) in enumerate(_PARTY_BUFFS):
            lbl = QLabel(display)
            party_grid.addWidget(lbl, row_i, 0)

            if wtype == "spin":
                combo = LevelWidget(max_lv, include_off=True)
                self._party_level_combos[sc_key] = combo
                combo.valueChanged.connect(self._on_changed)
                party_grid.addWidget(combo, row_i, 1)

            elif wtype == "check":
                chk = QCheckBox()
                self._party_checks[sc_key] = chk
                chk.toggled.connect(self._on_changed)
                party_grid.addWidget(chk, row_i, 1)

            elif wtype == "adrenaline":
                chk = QCheckBox()
                self._party_checks[sc_key] = chk
                combo = NoWheelCombo()
                combo.addItem("Self")
                combo.addItem("Party member")
                combo.setEnabled(False)
                self._party_combos[sc_key] = combo
                chk.toggled.connect(combo.setEnabled)
                chk.toggled.connect(self._on_changed)
                combo.currentIndexChanged.connect(self._on_changed)
                party_grid.addWidget(chk, row_i, 1)
                party_grid.addWidget(combo, row_i, 2)

            elif wtype == "check_or_spin":
                # Container holds both widgets; visibility toggled in set_server().
                # Vanilla: checkbox shown (stores 1), spin hidden.
                # PS: spin shown (stores level 1-5), checkbox hidden.
                _cos_container = QWidget()
                _cos_lay = QHBoxLayout(_cos_container)
                _cos_lay.setContentsMargins(0, 0, 0, 0)
                _cos_lay.setSpacing(0)
                chk = QCheckBox()
                self._party_checks[sc_key] = chk
                self._ot_party_chk = chk
                chk.toggled.connect(self._on_changed)
                _cos_lay.addWidget(chk)
                spin = LevelWidget(max_lv, include_off=True)
                self._party_level_combos[sc_key] = spin
                self._ot_party_spin = spin
                spin.valueChanged.connect(self._on_changed)
                spin.setVisible(False)  # hidden until set_server("payon_stories")
                _cos_lay.addWidget(spin)
                _cos_lay.addStretch()
                party_grid.addWidget(_cos_container, row_i, 1)

            elif wtype == "endow":
                combo = NoWheelCombo()
                for label, sc_val in _SAGE_ENDOW_OPTIONS:
                    combo.addItem(label, sc_val)
                self._endow_combo = combo
                combo.currentIndexChanged.connect(self._on_changed)
                party_grid.addWidget(combo, row_i, 1)
                # PS-only: Lv1 SA_* endow grants SC_IMPOSITIO_MANUS Lv5 (+25 weapon ATK)
                lv1_chk = QCheckBox("Lv1")
                lv1_chk.setObjectName("passive_sc_check")
                lv1_chk.setToolTip(
                    "Level 1 Sage endow (SA_FLAMELAUNCHER / SA_FROSTWEAPON /\n"
                    "SA_LIGHTNINGLOADER / SA_SEISMICWEAPON) grants\n"
                    "SC_IMPOSITIO_MANUS Lv5 (+25 weapon ATK) for 120s.\n"
                    "Only available on Payon Stories."
                )
                lv1_chk.setVisible(False)  # shown only when server == payon_stories
                lv1_chk.toggled.connect(self._on_changed)
                self._endow_lv1_check = lv1_chk
                party_grid.addWidget(lv1_chk, row_i, 2)

        # ── Sage Area (ground effects) row — appended at bottom of party grid ──
        _ground_row = len(_PARTY_BUFFS)
        party_grid.addWidget(QLabel("Sage Area:"), _ground_row, 0)

        _ground_inner = QWidget()
        _ground_lay = QHBoxLayout(_ground_inner)
        _ground_lay.setContentsMargins(0, 0, 0, 0)
        _ground_lay.setSpacing(6)

        self._ground_combo = NoWheelCombo()
        self._ground_combo.addItem("— (none)")
        self._ground_combo.addItem("Volcano")
        self._ground_combo.addItem("Deluge")
        self._ground_combo.addItem("Violent Gale")
        _ground_lay.addWidget(self._ground_combo)

        _lv_lbl = QLabel("Lv:")
        _lv_lbl.setObjectName("passive_sub_header")
        _ground_lay.addWidget(_lv_lbl)

        self._ground_lv_combo = LevelWidget(5, include_off=False)
        self._ground_lv_combo.setValue(5)
        self._ground_lv_combo.setEnabled(False)
        _ground_lay.addWidget(self._ground_lv_combo)

        self._ground_note = QLabel("(requires matching armor element)")
        self._ground_note.setObjectName("passive_note")
        _ground_lay.addWidget(self._ground_note)
        _ground_lay.addStretch()

        self._ground_combo.currentIndexChanged.connect(self._on_ground_changed)
        self._ground_lv_combo.currentIndexChanged.connect(self._on_changed)
        party_grid.addWidget(_ground_inner, _ground_row, 1, 1, 2)

        self._sub_party.add_content_widget(party_widget)
        self.add_content_widget(self._sub_party)

        # ── 3. Songs & Dances ────────────────────────────────────────────────
        self._sub_songs_dances = CollapsibleSubGroup("Songs & Dances", default_collapsed=True)
        self._sub_songs_dances.add_content_widget(self._build_songs_dances_widget())
        self.add_content_widget(self._sub_songs_dances)

        # ── 5. Ensembles ─────────────────────────────────────────────────────
        self._sub_ensemble = CollapsibleSubGroup("Ensembles", default_collapsed=True)
        self._sub_ensemble.add_content_widget(self._build_ensemble_widget())
        self.add_content_widget(self._sub_ensemble)

        # ── 6. Guild Buffs (stub) ─────────────────────────────────────────
        self._sub_guild = CollapsibleSubGroup("Guild Buffs", default_collapsed=True)
        self._sub_guild.add_content_widget(_stub_label("(Guild skills)"))
        self.add_content_widget(self._sub_guild)

        # ── 7. Miscellaneous Effects ───────────────────────────────────────
        self._sub_misc = CollapsibleSubGroup("Miscellaneous Effects", default_collapsed=False)

        misc_widget = QWidget()
        misc_grid = QGridLayout(misc_widget)
        misc_grid.setContentsMargins(0, 0, 0, 4)
        misc_grid.setSpacing(4)

        # Clan row (PS-only)
        self._clan_label = QLabel("Clan")
        self._clan_label.setObjectName("combat_field_label")
        self._combo_clan = NoWheelCombo()
        for clan_key, clan_label in _CLAN_ITEMS:
            self._combo_clan.addItem(clan_label, userData=clan_key)
        misc_grid.addWidget(self._clan_label, 0, 0)
        misc_grid.addWidget(self._combo_clan, 0, 1)

        # Pet row (both servers)
        self._pet_label = QLabel("Pet")
        self._pet_label.setObjectName("combat_field_label")
        self._combo_pet = NoWheelCombo()
        for pet_key, pet_label in _PET_ITEMS:
            self._combo_pet.addItem(pet_label, userData=pet_key)
        misc_grid.addWidget(self._pet_label, 1, 0)
        misc_grid.addWidget(self._combo_pet, 1, 1)

        self._sub_misc.add_content_widget(misc_widget)
        self.add_content_widget(self._sub_misc)
        self._combo_clan.currentIndexChanged.connect(self._on_changed)
        self._combo_pet.currentIndexChanged.connect(self._on_changed)
        self.set_header_summary(self._build_summary())

    def _on_ground_changed(self) -> None:
        if self._ground_lv_combo is not None:
            self._ground_lv_combo.setEnabled(self._ground_combo.currentIndex() != 0)
        self._on_changed()

    # ── Song/Dance widget builders ─────────────────────────────────────────

    def _build_songs_dances_widget(self) -> QWidget:
        """Combined Songs & Dances widget: bard songs, divider, dancer dances.

        Each row: [skill name] [level] [stat spin(s)] [Lesson dropdown]
        Stats are always-on — no override checkbox.
        """
        w = QWidget()
        grid = QGridLayout(w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(3)
        grid.setColumnStretch(0, 1)

        row = 0
        for sc_key, source_skill, stat_specs in _BARD_SONGS:
            self._add_song_dance_row(grid, row, sc_key, source_skill, stat_specs,
                                     self._song_level_combos, "Mus.Lesson",
                                     label_store=self._bard_song_labels)
            row += 1

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("section_separator")
        grid.addWidget(sep, row, 0, 1, -1)
        row += 1

        for sc_key, source_skill, stat_specs in _DANCER_DANCES:
            self._add_song_dance_row(grid, row, sc_key, source_skill, stat_specs,
                                     self._dance_level_combos, "D.Lesson",
                                     label_store=self._dance_labels)
            row += 1

        return w

    def _add_song_dance_row(self, grid: QGridLayout, row: int,
                             sc_key: str, source_skill: str,
                             stat_specs: list[tuple[str, str]],
                             level_store: dict[str, LevelWidget],
                             lesson_label: str,
                             label_store: dict[str, QLabel] | None = None) -> None:
        """Add one song/dance row: name, level, per-stat spins, lesson dropdown."""
        lbl = QLabel(loader.get_skill_display_name(source_skill))
        if label_store is not None:
            label_store[sc_key] = lbl
        grid.addWidget(lbl, row, 0)

        lv_combo = LevelWidget(10, include_off=True)
        level_store[sc_key] = lv_combo
        lv_combo.valueChanged.connect(self._on_changed)
        grid.addWidget(lv_combo, row, 1)

        ll = QLabel(f"{lesson_label}:")
        ll.setObjectName("passive_sub_header")
        grid.addWidget(ll, row, 2)
        lesson = LevelWidget(10, include_off=True)
        lesson.setValue(10)
        self._song_lesson_combos[sc_key] = lesson
        lesson.valueChanged.connect(self._on_changed)
        grid.addWidget(lesson, row, 3)

        self._song_stat_spins[sc_key] = {}
        col = 4
        for stat_key, stat_label in stat_specs:
            s_lbl = QLabel(f"{stat_label}:")
            s_lbl.setObjectName("passive_sub_header")
            grid.addWidget(s_lbl, row, col)
            col += 1
            spin = NoWheelSpin()
            spin.setRange(1, 255)
            spin.setValue(1)
            spin.setFixedWidth(52)
            self._song_stat_spins[sc_key][stat_key] = spin
            spin.valueChanged.connect(self._on_changed)
            grid.addWidget(spin, row, col)
            col += 1

    def _build_ensemble_widget(self) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(3)
        note = QLabel("(simplified: WATK/resist effects not implemented)")
        note.setObjectName("passive_sub_header")
        grid.addWidget(note, 0, 0, 1, 4)
        for r, (sc_key, source_skill, max_lv) in enumerate(_ENSEMBLES, start=1):
            lbl = QLabel(loader.get_skill_display_name(source_skill))
            self._ensemble_labels[sc_key] = lbl
            grid.addWidget(lbl, r, 0)
            combo = LevelWidget(max_lv, include_off=True)
            self._ensemble_combos[sc_key] = combo
            combo.valueChanged.connect(self._on_changed)
            grid.addWidget(combo, r, 1)
        return w

    # ── Job filtering ──────────────────────────────────────────────────────

    def update_job(self, job_id: int) -> None:
        self._current_job_id = job_id
        show_all = self._show_all_chk.isChecked()
        job_skills = loader.get_skills_for_job(job_id)
        for sc_key, source_skill, has_lv, _min, _max in _SELF_BUFFS:
            if sc_key in _PS_ONLY_SC_KEYS:
                # PS-only: hidden in standard mode; job-restricted unless Show All is on.
                visible = (self._current_server == "payon_stories") and (
                    show_all or job_id in _PS_SC_JOB_RESTRICTION.get(sc_key, frozenset())
                )
            elif sc_key in _VANILLA_ONLY_SC_KEYS:
                # vanilla-only: hidden in PS mode regardless of Show All.
                visible = (self._current_server != "payon_stories") and (
                    show_all or source_skill in job_skills
                )
            else:
                visible = show_all or (source_skill in job_skills)
            for w in self._self_buff_widgets.get(sc_key, []):
                w.setVisible(visible)
            if not visible:
                if has_lv and sc_key in self._sc_combos:
                    self._sc_combos[sc_key].blockSignals(True)
                    self._sc_combos[sc_key].setCurrentIndex(0)
                    self._sc_combos[sc_key].blockSignals(False)
                elif sc_key == "_GS_STANCE" and self._gs_stance_combo is not None:
                    self._gs_stance_combo.blockSignals(True)
                    self._gs_stance_combo.setCurrentIndex(0)
                    self._gs_stance_combo.blockSignals(False)
                elif sc_key in self._sc_checks:
                    chk = self._sc_checks[sc_key]
                    chk.blockSignals(True)
                    chk.setChecked(False)
                    chk.blockSignals(False)

    def set_server(self, server: str) -> None:
        self._current_server = server
        if self._endow_lv1_check is not None:
            visible = server == "payon_stories"
            self._endow_lv1_check.setVisible(visible)
            if not visible:
                self._endow_lv1_check.blockSignals(True)
                self._endow_lv1_check.setChecked(False)
                self._endow_lv1_check.blockSignals(False)
        # PS caps ground effect levels at 3; removes armor element restriction note.
        is_ps = server == "payon_stories"
        if self._ground_note is not None:
            self._ground_note.setVisible(not is_ps)
        if self._ground_lv_combo is not None:
            self._ground_lv_combo.set_max(3 if is_ps else 5)
        # Clan dropdown is PS-only
        self._clan_label.setVisible(is_ps)
        self._combo_clan.setVisible(is_ps)
        if not is_ps:
            self._combo_clan.blockSignals(True)
            self._combo_clan.setCurrentIndex(0)
            self._combo_clan.blockSignals(False)
        # SC_OVERTHRUST party: checkbox on vanilla, spin on PS.
        if self._ot_party_chk is not None and self._ot_party_spin is not None:
            if is_ps:
                self._ot_party_chk.setVisible(False)
                self._ot_party_chk.blockSignals(True)
                self._ot_party_chk.setChecked(False)
                self._ot_party_chk.blockSignals(False)
                self._ot_party_spin.setVisible(True)
            else:
                self._ot_party_spin.setVisible(False)
                self._ot_party_spin.blockSignals(True)
                self._ot_party_spin.setValue(0)
                self._ot_party_spin.blockSignals(False)
                self._ot_party_chk.setVisible(True)
        self.update_job(self._current_job_id)
        self._refresh_server_labels(server)

    def _refresh_server_labels(self, server: str) -> None:
        """Update all skill-name labels and combo items for the given server."""
        profile = get_profile(server)
        for sc_key, source_skill, has_lv, _, _ in _SELF_BUFFS:
            if sc_key in _SELF_BUFF_CUSTOM_LABELS:
                continue  # custom labels are server-invariant
            new_text = loader.get_skill_display_name(source_skill, profile)
            widgets = self._self_buff_widgets.get(sc_key, [])
            if has_lv or sc_key == "_GS_STANCE":
                if widgets:
                    widgets[0].setText(new_text)
            else:
                chk = self._sc_checks.get(sc_key)
                if chk:
                    chk.setText(new_text)
        for sc_key, source_skill, _ in _BARD_SONGS:
            if sc_key in self._bard_song_labels:
                self._bard_song_labels[sc_key].setText(
                    loader.get_skill_display_name(source_skill, profile))
        for sc_key, source_skill, _ in _DANCER_DANCES:
            if sc_key in self._dance_labels:
                self._dance_labels[sc_key].setText(
                    loader.get_skill_display_name(source_skill, profile))
        for sc_key, source_skill, _ in _ENSEMBLES:
            if sc_key in self._ensemble_labels:
                self._ensemble_labels[sc_key].setText(
                    loader.get_skill_display_name(source_skill, profile))
        if self._gs_stance_combo is not None:
            self._gs_stance_combo.setItemText(
                1, loader.get_skill_display_name("GS_MADNESSCANCEL", profile))
            self._gs_stance_combo.setItemText(
                2, loader.get_skill_display_name("GS_ADJUSTMENT", profile))

    # ── Internal ───────────────────────────────────────────────────────────

    def _on_show_all_toggled(self, _: bool) -> None:
        self.update_job(self._current_job_id)

    def _on_changed(self) -> None:
        self.changed.emit()
        self.set_header_summary(self._build_summary())

    def _build_summary(self) -> str:
        parts: list[str] = []
        for sc_key, source_skill, has_lv, *_ in _SELF_BUFFS:
            label = _resolve_self_buff_label(sc_key, source_skill, self._current_server)
            if has_lv:
                val = self._sc_combos[sc_key].value() if sc_key in self._sc_combos else 0
                if val > 0:
                    parts.append(f"{label} {val}")
            elif sc_key == "_GS_STANCE":
                if self._gs_stance_combo is not None and self._gs_stance_combo.currentIndex() > 0:
                    parts.append(self._gs_stance_combo.currentText())
            else:
                chk = self._sc_checks.get(sc_key)
                if chk and chk.isChecked():
                    parts.append(label)
        return "  ·  ".join(parts) if parts else "No active buffs"

    # ── Public API ─────────────────────────────────────────────────────────

    def set_spirit_spheres(self, n: int) -> None:
        """Sync MO_SPIRITBALL combo from combat param change; no recalc (combat already triggers it)."""
        combo = self._sc_combos.get("MO_SPIRITBALL")
        if combo is None:
            return
        combo.blockSignals(True)
        combo.setValue(n)
        combo.blockSignals(False)
        self.set_header_summary(self._build_summary())

    def load_build(self, build: PlayerBuild) -> None:
        # Collect all blockable widgets
        _all_widgets: list[QWidget] = (
            list(self._sc_checks.values()) +
            list(self._sc_combos.values()) +
            list(self._party_level_combos.values()) +
            list(self._party_checks.values()) +
            list(self._party_combos.values()) +
            list(self._song_level_combos.values()) +
            list(self._dance_level_combos.values()) +
            list(self._song_lesson_combos.values()) +
            list(self._ensemble_combos.values())
        )
        for stat_d in self._song_stat_spins.values():
            _all_widgets.extend(stat_d.values())
        if self._endow_combo is not None:
            _all_widgets.append(self._endow_combo)
        if self._endow_lv1_check is not None:
            _all_widgets.append(self._endow_lv1_check)
        if self._ground_combo is not None:
            _all_widgets.append(self._ground_combo)
        if self._ground_lv_combo is not None:
            _all_widgets.append(self._ground_lv_combo)
        if self._gs_stance_combo is not None:
            _all_widgets.append(self._gs_stance_combo)
        _all_widgets.append(self._combo_clan)
        _all_widgets.append(self._combo_pet)
        for w in _all_widgets:
            w.blockSignals(True)

        # Self buffs
        active = build.active_status_levels
        for sc_key, _, has_lv, min_lv, *_ in _SELF_BUFFS:
            if has_lv:
                self._sc_combos[sc_key].setValue(active.get(sc_key, 0))
            elif sc_key == "_GS_STANCE":
                pass  # handled below
            elif sc_key == "SC_ADRENALINE_SELF":
                pass  # handled after party buffs loading
            else:
                chk = self._sc_checks[sc_key]
                chk.setChecked(sc_key in active)
        # GS Stance combo
        if self._gs_stance_combo is not None:
            if "SC_GS_MADNESSCANCEL" in active:
                self._gs_stance_combo.setCurrentIndex(1)
            elif "SC_GS_ADJUSTMENT" in active:
                self._gs_stance_combo.setCurrentIndex(2)
            else:
                self._gs_stance_combo.setCurrentIndex(0)

        # Party buffs
        support = build.support_buffs
        for sc_key, _, wtype, *_ in _PARTY_BUFFS:
            if wtype == "spin":
                self._party_level_combos[sc_key].setValue(int(support.get(sc_key, 0)))
            elif wtype == "check":
                self._party_checks[sc_key].setChecked(bool(support.get(sc_key, False)))
            elif wtype == "check_or_spin":
                if build.server == "payon_stories":
                    self._party_level_combos[sc_key].setValue(int(support.get(sc_key, 0)))
                else:
                    self._party_checks[sc_key].setChecked(bool(support.get(sc_key, False)))
            elif wtype == "endow" and self._endow_combo is not None:
                stored = support.get("weapon_endow_sc")
                idx = self._endow_combo.findData(stored)
                self._endow_combo.setCurrentIndex(idx if idx >= 0 else 0)
                if self._endow_lv1_check is not None:
                    self._endow_lv1_check.setChecked(bool(support.get("endow_lv1", False)))

        # SC_ADRENALINE: restore self/party toggles from stored val3.
        # Party "check" loop set party toggle from bool(val); correct it now.
        _adr_val = int(support.get("SC_ADRENALINE", 0))
        _adr_self = self._sc_checks.get("SC_ADRENALINE_SELF")
        if _adr_self is not None:
            _adr_self.setChecked(_adr_val == 300)
        _adr_party = self._party_checks.get("SC_ADRENALINE")
        if _adr_party is not None:
            _adr_party.setChecked(_adr_val == 200)

        # Songs/dances
        ss = build.song_state
        for sc_key, _, stat_specs in _BARD_SONGS:
            self._song_level_combos[sc_key].setValue(int(ss.get(sc_key, 0)))
            for stat_key, _ in stat_specs:
                self._song_stat_spins[sc_key][stat_key].setValue(int(ss.get(f"{sc_key}_{stat_key}") or 1))
            self._song_lesson_combos[sc_key].setValue(int(ss.get(f"{sc_key}_lesson", 10)))
        for sc_key, _, stat_specs in _DANCER_DANCES:
            self._dance_level_combos[sc_key].setValue(int(ss.get(sc_key, 0)))
            for stat_key, _ in stat_specs:
                self._song_stat_spins[sc_key][stat_key].setValue(int(ss.get(f"{sc_key}_{stat_key}") or 1))
            self._song_lesson_combos[sc_key].setValue(int(ss.get(f"{sc_key}_lesson", 10)))
        for sc_key, _, _ in _ENSEMBLES:
            if sc_key == "SC_SIEGFRIED":
                self._ensemble_combos[sc_key].setValue(int(build.support_buffs.get(sc_key, 0)))
            else:
                self._ensemble_combos[sc_key].setValue(int(ss.get(sc_key, 0)))

        # Ground effects
        if self._ground_combo is not None and self._ground_lv_combo is not None:
            ge = support.get("ground_effect")
            ge_idx = _GROUND_SC_KEYS.index(ge) if ge in _GROUND_SC_KEYS else 0
            _ge_max = 3 if build.server == "payon_stories" else 5
            self._ground_lv_combo.rebuild_max(_ge_max)
            self._ground_combo.setCurrentIndex(ge_idx)
            self._ground_lv_combo.setValue(min(int(support.get("ground_effect_lv", 1)), _ge_max))
            self._ground_lv_combo.setEnabled(ge_idx != 0)

        # Clan
        clan_key = build.clan or ""
        for i, (key, _) in enumerate(_CLAN_ITEMS):
            if key == clan_key:
                self._combo_clan.setCurrentIndex(i)
                break
        else:
            self._combo_clan.setCurrentIndex(0)

        # Pet
        pet_key = build.selected_pet or ""
        for i, (key, _) in enumerate(_PET_ITEMS):
            if key == pet_key:
                self._combo_pet.setCurrentIndex(i)
                break
        else:
            self._combo_pet.setCurrentIndex(0)

        for w in _all_widgets:
            w.blockSignals(False)

        self._current_job_id = build.job_id
        self._current_server = build.server
        self.update_job(build.job_id)
        self._refresh_server_labels(build.server)

        self.set_header_summary(self._build_summary())


    def collect_into(self, build: PlayerBuild) -> None:
        # Self buffs → active_status_levels
        active: dict[str, int] = build.active_status_levels.copy()
        for sc_key, *_ in _SELF_BUFFS:
            active.pop(sc_key, None)
        # also clear the two real SC keys replaced by the stance sentinel
        active.pop("SC_GS_MADNESSCANCEL", None)
        active.pop("SC_GS_ADJUSTMENT", None)
        for sc_key, _, has_lv, min_lv, *_ in _SELF_BUFFS:
            if has_lv:
                val = self._sc_combos[sc_key].value() if sc_key in self._sc_combos else 0
                if val > 0:
                    active[sc_key] = val
            elif sc_key == "_GS_STANCE":
                pass  # handled below
            elif sc_key == "SC_ADRENALINE_SELF":
                pass  # handled after party buffs; writes to support_buffs["SC_ADRENALINE"]
            else:
                chk = self._sc_checks.get(sc_key)
                if chk and chk.isChecked():
                    active[sc_key] = min_lv
        # GS Stance combo → set the appropriate SC key
        if self._gs_stance_combo is not None:
            idx = self._gs_stance_combo.currentIndex()
            if idx == 1:
                active["SC_GS_MADNESSCANCEL"] = 1
            elif idx == 2:
                active["SC_GS_ADJUSTMENT"] = 1
        build.active_status_levels = active

        # Party buffs → support_buffs
        support: dict[str, object] = build.support_buffs.copy()
        for sc_key, *_ in _PARTY_BUFFS:
            support.pop(sc_key, None)
        for sc_key, _, wtype, *_ in _PARTY_BUFFS:
            if wtype == "spin":
                val = self._party_level_combos[sc_key].value()
                if val > 0:
                    support[sc_key] = val
            elif wtype == "check":
                if self._party_checks[sc_key].isChecked():
                    support[sc_key] = 1
            elif wtype == "check_or_spin":
                if self._current_server == "payon_stories":
                    val = self._party_level_combos[sc_key].value()
                    if val > 0:
                        support[sc_key] = val
                else:
                    if self._party_checks[sc_key].isChecked():
                        support[sc_key] = 1
            elif wtype == "endow" and self._endow_combo is not None:
                val = self._endow_combo.currentData()
                if val is not None:
                    support["weapon_endow_sc"] = val
                # PS Lv1 side effect: track separately; base_damage.py merges with spin value
                support.pop("endow_lv1", None)
                if self._endow_lv1_check is not None and self._endow_lv1_check.isChecked():
                    support["endow_lv1"] = True

        # SC_ADRENALINE: resolve val3 — self (BS/WS, val3=300) takes priority over party (val3=200).
        # The party "check" loop wrote support["SC_ADRENALINE"] = 1 if party toggle is on; override here.
        _adr_self = self._sc_checks.get("SC_ADRENALINE_SELF")
        if _adr_self and _adr_self.isChecked():
            support["SC_ADRENALINE"] = 300
        elif support.get("SC_ADRENALINE"):  # party toggle wrote 1
            support["SC_ADRENALINE"] = 200
        # SC_ADRENALINE2: always party buff; party toggle wrote 1 → convert to val3=200.
        if support.get("SC_ADRENALINE2"):
            support["SC_ADRENALINE2"] = 200

        # Ground effects
        support.pop("ground_effect", None)
        support.pop("ground_effect_lv", None)
        if self._ground_combo is not None and self._ground_combo.currentIndex() != 0:
            support["ground_effect"] = _GROUND_SC_KEYS[self._ground_combo.currentIndex()]
            support["ground_effect_lv"] = self._ground_lv_combo.value() or 1
        build.support_buffs = support

        # Songs/dances → song_state
        ss: dict[str, object] = {}
        for sc_key, _, stat_specs in _BARD_SONGS:
            ss[sc_key] = self._song_level_combos[sc_key].value()
            for stat_key, _ in stat_specs:
                ss[f"{sc_key}_{stat_key}"] = self._song_stat_spins[sc_key][stat_key].value()
            ss[f"{sc_key}_lesson"] = self._song_lesson_combos[sc_key].value()
        for sc_key, _, stat_specs in _DANCER_DANCES:
            ss[sc_key] = self._dance_level_combos[sc_key].value()
            for stat_key, _ in stat_specs:
                ss[f"{sc_key}_{stat_key}"] = self._song_stat_spins[sc_key][stat_key].value()
            ss[f"{sc_key}_lesson"] = self._song_lesson_combos[sc_key].value()
        for sc_key, _, _ in _ENSEMBLES:
            if sc_key == "SC_SIEGFRIED":
                build.support_buffs["SC_SIEGFRIED"] = self._ensemble_combos[sc_key].value()
            else:
                ss[sc_key] = self._ensemble_combos[sc_key].value()
        build.song_state = ss

        # Clan (PS-only; harmless to write on standard — apply_gear_bonuses ignores unknown keys)
        build.clan = self._combo_clan.currentData() or ""
        build.selected_pet = self._combo_pet.currentData() or ""

