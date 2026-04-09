"""
gear_bonus_aggregator — Aggregate item script bonuses from all equipped slots into GearBonuses.

Input:  build.equipped (slot → item_id), build.refine_levels, ItemScriptContext
Output: GearBonuses — consumed by StatusCalculator (status_calculator.py),
        MasteryFix (mastery_fix.py), SkillRatio (skill_ratio.py), and all pipeline steps
        that read add_ele / add_race / sub_ele / sub_race.

_apply() is table-driven via BONUS1/BONUS2 from bonus_definitions.py.

GearBonuses.effective_mastery — merged dict of build mastery_levels + skill_grants from
item scripts; consumed by MasteryFix (mastery_fix.py) and SkillRatio (skill_ratio.py).

script_ctx_from_build() is called twice by resolve_player_state() (player_state_builder.py):
once without hp/sp context (pass 1) and once with hp/sp from pass-1 status (pass 2).
"""
from __future__ import annotations

import dataclasses
from typing import Dict, Optional

from core.bonus_definitions import BONUS1, BONUS2, _ELE_STR_TO_INT

# pc.c:3169-3185 + map.h:392-412 — composite race constants fan out at storage time.
# bAddRace,RC_DemiPlayer stores into addrace[RC_DemiHuman] + addrace[RC_Player], etc.
# Keys in this dict must never appear as stored keys in add_race / magic_add_race.
_RC_FANOUT: dict[str, tuple[str, ...]] = {
    "RC_All":           ("RC_Boss", "RC_NonBoss"),
    "RC_DemiPlayer":    ("RC_DemiHuman", "RC_Player"),
    "RC_NonDemiPlayer": ("RC_Formless", "RC_Undead", "RC_Brute", "RC_Plant",
                         "RC_Insect", "RC_Fish", "RC_Demon", "RC_Angel", "RC_Dragon"),
    "RC_NonPlayer":     ("RC_Formless", "RC_Undead", "RC_Brute", "RC_Plant",
                         "RC_Insect", "RC_Fish", "RC_Demon", "RC_DemiHuman", "RC_Angel", "RC_Dragon"),
}
from core.data_loader import loader
from core.item_script_parser import ItemScriptContext, parse_sc_start, parse_script, _make_description
from core.models.autocast_spec import AutocastSpec
from core.models.build import PlayerBuild
from core.models.gear_bonuses import GearBonuses
from core.models.item_effect import ItemEffect


def script_ctx_from_build(build: PlayerBuild, status=None) -> ItemScriptContext:
    """Build an ItemScriptContext from a PlayerBuild.

    Populates all fields that are available at gear-aggregation time:
      - base stats (sd->status.str etc. via pc_readparam — base points, not total)
      - base_level, job_level, class_
      - skill_levels from mastery_levels (covers passive mastery skill checks;
        non-mastery getskilllv conditions fall through conservatively until a
        full skill_levels dict is added to PlayerBuild)

    status: if provided (pass-2 of resolve_player_state), max_hp/max_sp are taken
      from status.max_hp/max_sp. hp defaults to build.current_hp, or max_hp if None
      (full-health assumption). sp defaults to build.current_sp, or max_sp if None.
      Pass None (pass-1) to leave hp/sp/max_hp/max_sp absent — conditions on these
      fall through conservatively, acceptable only as an intermediate result.

    refine is set to 0 here; GearBonusAggregator.compute() overrides it per-slot.
    """
    if status is not None:
        max_hp = status.max_hp
        max_sp = status.max_sp
        hp = build.current_hp if build.current_hp is not None else max_hp
        sp = build.current_sp if build.current_sp is not None else max_sp
    else:
        max_hp = max_sp = hp = sp = None

    return ItemScriptContext(
        refine=0,
        skill_levels=dict(build.mastery_levels),
        base_level=build.base_level,
        job_level=build.job_level,
        str_=build.base_str,
        agi=build.base_agi,
        vit=build.base_vit,
        int_=build.base_int,
        dex=build.base_dex,
        luk=build.base_luk,
        class_=build.job_id,
        hp=hp,
        sp=sp,
        max_hp=max_hp,
        max_sp=max_sp,
    )


class GearBonusAggregator:

    @staticmethod
    def compute(
        equipped: Dict[str, Optional[int]],
        refine_levels: Optional[Dict[str, int]] = None,
        script_ctx: Optional[ItemScriptContext] = None,
    ) -> GearBonuses:
        """
        Parse scripts for all equipped item IDs and aggregate into GearBonuses.
        Slots with None or unknown IDs are silently skipped.

        refine_levels: build.refine_levels — used to compute armor refine DEF.
          If None, armor refine DEF is skipped (backward-compatible).

        script_ctx: player-side runtime context for evaluating item script conditionals
          (getskilllv, readparam, BaseLevel, etc.). Per-slot refine is overridden from
          refine_levels automatically. Pass None for the prior conservative behaviour.
        """
        bonuses = GearBonuses()
        card_gb = GearBonuses()   # card-only sub-aggregate (from_cards)
        refinedef_units = 0  # accumulated raw units; rounding applied once after loop

        for slot, item_id in equipped.items():
            if item_id is None:
                continue
            item = loader.get_item(item_id)
            if item is None:
                continue

            if item.get("type") == "IT_ARMOR":
                # F2: sum base DEF from IT_ARMOR items (item["def"] field)
                bonuses.def_ += item.get("def", 0)
                # Armor refine DEF — accumulate raw units, round aggregate at end.
                # status.c ~1655: refinedef += refine->get_bonus(REFINE_TYPE_ARMOR, r)
                # Skip non-refineable items (e.g. mid/lower headgear, accessories).
                if refine_levels is not None and item.get("refineable", True):
                    r = refine_levels.get(slot, 0)
                    if r > 0:
                        refinedef_units += loader.get_armor_refine_units(r)

            script = item.get("script") or ""
            if not script:
                continue

            # Cards inherit the host item's refine for getrefine() evaluation.
            # e.g. 'armor_card' → 'armor', 'right_hand_card_1' → 'right_hand'
            # Source: pc.c — getrefine() returns sd->inventory.u.items_w[n].refine
            # where n is the slot the card is compounded into, not the card's own slot.
            refine_slot = slot[:slot.index("_card")] if "_card" in slot else slot
            refine = (refine_levels or {}).get(refine_slot, 0)

            # Inject weapon_level for card slots so getequipweaponlv() can be evaluated.
            # Source: script.c:10731 — getequipweaponlv returns sd->inventory_data[i]->wlv,
            # where i is the slot the card is compounded into.
            weapon_level: int | None = None
            if "_card" in slot:
                host_item_id = equipped.get(refine_slot)
                if host_item_id is not None:
                    host_item = loader.get_item(host_item_id)
                    if host_item is None:
                        raise ValueError(
                            f"Card slot {slot!r}: host item id {host_item_id} not found in item DB"
                        )
                    # Only weapons carry a 'level' (wlv) field.
                    # Armor/accessory/etc. hosts leave weapon_level=None.
                    # If a non-weapon card script somehow contains getequipweaponlv(),
                    # preprocess_script() will raise at parse time.
                    if host_item.get("type") == "IT_WEAPON":
                        wlv = host_item.get("level")
                        if wlv is None:
                            raise ValueError(
                                f"Card slot {slot!r}: weapon host {host_item_id} has no 'level' field"
                            )
                        weapon_level = wlv

            if script_ctx is not None:
                ctx = dataclasses.replace(script_ctx, refine=refine, weapon_level=weapon_level)
            else:
                ctx = ItemScriptContext(refine=refine, weapon_level=weapon_level)

            effects = parse_script(script, ctx)

            # Tag every effect with its origin before adding to all_effects.
            for eff in effects:
                eff.source_slot = slot
                eff.source_item_id = item_id
            bonuses.all_effects.extend(effects)

            # Card slots feed both the main aggregate and the card sub-aggregate.
            _is_card = "_card" in slot
            _targets = [bonuses, card_gb] if _is_card else [bonuses]

            for eff in effects:
                # bAtkEle on left_hand slot → lhw.ele (pc.c:2588-2609 lr_flag==1).
                # All other slots including right_hand use the default _apply path → rhw.ele.
                # left_hand is never a card slot, so _targets is always [bonuses] here.
                if eff.bonus_type == "bAtkEle" and slot == "left_hand":
                    if eff.arity == 1 and eff.params:
                        v = _ELE_STR_TO_INT.get(str(eff.params[0]))
                        if v is not None:
                            bonuses.script_atk_ele_lh = v
                # Autocast-2: intercept autocast bonus types before generic _apply().
                # _apply() only handles arity 1 and 2; autocast bonuses are arity 3/4.
                elif eff.bonus_type in ("bAutoSpell", "bAutoSpellWhenHit", "bAutoSpellOnSkill"):
                    for _t in _targets:
                        GearBonusAggregator._build_autocast_spec(_t, eff)
                elif eff.bonus_type == "skill":
                    # `skill X,N` grants the player skill X at level N temporarily.
                    # Source: Hercules script.c — pc_skill(sd, id, lv, ADDSKILL_TEMP)
                    _sk_name = str(eff.params[0])
                    _sk_lv   = eff.params[1] if isinstance(eff.params[1], int) else 1
                    for _t in _targets:
                        _t.skill_grants[_sk_name] = max(
                            _t.skill_grants.get(_sk_name, 0), _sk_lv
                        )
                else:
                    for _t in _targets:
                        GearBonusAggregator._apply(_t, eff)

            bonuses.sc_effects.extend(parse_sc_start(script, ctx))

        # status.c ~1713: bstatus->def += (refinedef + 50) / 100
        if refinedef_units > 0:
            bonuses.def_ += (refinedef_units + 50) // 100

        # Attach card sub-aggregate. card_gb.effective_mastery is left empty —
        # it is a source-breakdown object, not an input to any calculation.
        bonuses.from_cards = card_gb

        # Compute effective_mastery: base mastery_levels merged with skill_grants (take max).
        # script_ctx.skill_levels IS mastery_levels (set in script_ctx_from_build).
        if script_ctx is not None:
            bonuses.effective_mastery = dict(script_ctx.skill_levels)
            for _name, _lv in bonuses.skill_grants.items():
                bonuses.effective_mastery[_name] = max(
                    bonuses.effective_mastery.get(_name, 0), _lv
                )
        else:
            bonuses.effective_mastery = dict(bonuses.skill_grants)

        return bonuses

    @staticmethod
    def apply_passive_bonuses(bonuses: GearBonuses, mastery_levels: dict,
                              profile=None) -> None:
        """Augment GearBonuses in-place with resist/race bonuses from passive skills.
        Call immediately after compute() wherever gear_bonuses feeds CardFix or DefenseFix.
        Source: status_calc_pc_ (status.c, #ifndef RENEWAL guards noted).

        profile: ServerProfile (optional). When provided, passive_overrides entries with
        addele_per_lv are applied to bonuses.add_ele.
        """
        # CR_TRUST: subele[Ele_Holy] += lv*5 (status.c:2187)
        cr_trust_lv = mastery_levels.get("CR_TRUST", 0)
        if cr_trust_lv:
            bonuses.sub_ele["Ele_Holy"] = bonuses.sub_ele.get("Ele_Holy", 0) + cr_trust_lv * 5

        # BS_SKINTEMPER: handled in player_build_to_target() with PS/vanilla branching.
        # (vanilla: Neutral +lv%, Fire +4*lv%; PS: Neutral +4*lv%, Fire +6*lv%)
        # Do NOT apply here — would double-count with build_manager.py:player_build_to_target.

        # SA_DRAGONOLOGY: #ifndef RENEWAL addrace[RC_Dragon] += lv*4 (weapon+magic); subrace[RC_Dragon] += lv*4
        # (status.c:2197–2210): right_weapon.addrace, left_weapon.addrace, magic_addrace, subrace all get lv*4
        sa_dragon_lv = mastery_levels.get("SA_DRAGONOLOGY", 0)
        if sa_dragon_lv:
            bonuses.add_race["RC_Dragon"] = bonuses.add_race.get("RC_Dragon", 0) + sa_dragon_lv * 4
            bonuses.magic_add_race["RC_Dragon"] = bonuses.magic_add_race.get("RC_Dragon", 0) + sa_dragon_lv * 4
            bonuses.sub_race["RC_Dragon"] = bonuses.sub_race.get("RC_Dragon", 0) + sa_dragon_lv * 4

        # Profile-driven addele_per_lv passives (e.g. AS_ENCHANTPOISON +2%/lv vs Ele_Poison).
        # Source: ps_skill_db.json (description field per skill).
        if profile is not None:
            for skill_key, spec in profile.passive_overrides.items():
                addele = spec.get("addele_per_lv")
                if not addele:
                    continue
                lv = mastery_levels.get(skill_key, 0)
                if lv > 0:
                    for ele_key, per_lv in addele.items():
                        bonuses.add_ele[ele_key] = bonuses.add_ele.get(ele_key, 0) + lv * per_lv

    @staticmethod
    def _apply(bonuses: GearBonuses, eff: ItemEffect) -> None:
        """Route one ItemEffect into the appropriate GearBonuses field."""
        bt = eff.bonus_type
        p = eff.params

        if eff.arity == 1 and p:
            defn = BONUS1.get(bt)
            if defn is None:
                return
            if defn.mode == "assign" and defn.field is not None:
                # Last-wins assignment; optional transform converts raw param to stored type.
                raw = p[0]
                v = defn.transform(raw) if defn.transform else raw
                if v is not None:
                    setattr(bonuses, defn.field, v)
            elif defn.mode == "dict_keys" and defn.field is not None and defn.keys:
                # Write int value to each fixed key (e.g. bIgnoreMdefRate → RC_NonBoss + RC_Boss).
                v = p[0] if isinstance(p[0], int) else 0
                d = getattr(bonuses, defn.field)
                for k in defn.keys:
                    d[k] = d.get(k, 0) + v
            elif defn.mode == "dict" and defn.field is not None and isinstance(p[0], str):
                # Arity-1 dict with string param: param is the key, value is 1 (presence flag).
                # Used by bDefRatioAtkRace arity-1 (e.g. bonus bDefRatioAtkRace,RC_All).
                d = getattr(bonuses, defn.field)
                d[p[0]] = d.get(p[0], 0) + 1
            else:
                v = p[0] if isinstance(p[0], int) else 0
                if defn.mode == "multi" and defn.fields:
                    for f in defn.fields:
                        setattr(bonuses, f, getattr(bonuses, f) + v)
                elif defn.field is not None:
                    setattr(bonuses, defn.field, getattr(bonuses, defn.field) + v)

        elif eff.arity == 2 and len(p) >= 2:
            defn = BONUS2.get(bt)
            if defn is None or defn.field is None:
                return
            key = str(p[0])
            val = p[1] if isinstance(p[1], int) else 0
            if defn.mode == "dict":
                d = getattr(bonuses, defn.field)
                if defn.field in ("add_race", "magic_add_race") and key in _RC_FANOUT:
                    for constituent in _RC_FANOUT[key]:
                        d[constituent] = d.get(constituent, 0) + val
                else:
                    d[key] = d.get(key, 0) + val
            elif defn.mode == "add":
                setattr(bonuses, defn.field, getattr(bonuses, defn.field) + val)

        # arity 3+: display-only for generic bonuses; autocast arities handled by _build_autocast_spec()

    @staticmethod
    def _build_autocast_spec(bonuses: GearBonuses, eff: ItemEffect) -> None:
        """Parse one autocast ItemEffect into an AutocastSpec and append to the correct list.

        bAutoSpell arity 3: params=[skill_name, skill_lv, rate]
        bAutoSpell arity 4: params=[skill_name, skill_lv, rate, flag]  (flag ignored — default BF_NORMAL)
        bAutoSpellWhenHit arity 3: params=[skill_name, skill_lv, rate]
        bAutoSpellWhenHit arity 4: params=[skill_name, skill_lv, rate, flag]
        bAutoSpellOnSkill arity 4: params=[src_skill, proc_skill, proc_lv, rate]
        bAutoSpellOnSkill arity 3: params=[src_skill, proc_skill, rate]  (proc_lv defaults to 1)

        Non-int skill_level (e.g. getskilllv() expression) → defaults to 1 (conservative, valid).
        Source: pc.c:3984 (SP_AUTOSPELL), pc.c:4200 (bonus4 bAutoSpell), pc.c:4215 (SP_AUTOSPELL_ONSKILL),
                pc.c:2105 (pc_bonus_autospell), pc.c:2143 (pc_bonus_autospell_onskill),
                skill.c:2472-2473 (BF_WEAPON|BF_NORMAL trigger), skill.c:2491 (ranged halving)
        """
        p = eff.params
        bt = eff.bonus_type

        if bt in ("bAutoSpell", "bAutoSpellWhenHit"):
            # params[0]=skill_name, params[1]=skill_lv, params[2]=rate
            if len(p) < 3:
                return
            skill_name = str(p[0])
            skill_id = loader.get_skill_id_by_name(skill_name)
            if skill_id is None:
                return
            skill_level = p[1] if isinstance(p[1], int) else 1
            rate = p[2] if isinstance(p[2], int) else 0
            spec = AutocastSpec(
                skill_id=skill_id,
                skill_level=skill_level,
                chance_per_mille=rate,
                when_hit=(bt == "bAutoSpellWhenHit"),
            )
            if bt == "bAutoSpellWhenHit":
                bonuses.autocast_when_hit.append(spec)
            else:
                bonuses.autocast_on_attack.append(spec)

        elif bt == "bAutoSpellOnSkill":
            # arity 4: params=[src_skill, proc_skill, proc_lv, rate]
            # arity 3: params=[src_skill, proc_skill, rate]  (no proc_lv; default 1)
            if len(p) < 3:
                return
            src_name  = str(p[0])
            proc_name = str(p[1])
            src_id  = loader.get_skill_id_by_name(src_name)
            proc_id = loader.get_skill_id_by_name(proc_name)
            if src_id is None or proc_id is None:
                return
            if len(p) >= 4:
                # arity 4: [src, proc, lv, rate]
                proc_lv = p[2] if isinstance(p[2], int) else 1
                rate    = p[3] if isinstance(p[3], int) else 0
            else:
                # arity 3: [src, proc, rate]
                proc_lv = 1
                rate    = p[2] if isinstance(p[2], int) else 0
            spec = AutocastSpec(
                skill_id=proc_id,
                skill_level=proc_lv,
                chance_per_mille=rate,
                src_skill_id=src_id,
            )
            bonuses.autocast_on_skill.append(spec)

    @staticmethod
    def apply_combo_bonuses(bonuses: GearBonuses, equipped: Dict[str, Optional[int]],
                            profile=None,
                            script_ctx: Optional[ItemScriptContext] = None) -> None:
        """Apply item combo bonuses from item_combo_db to bonuses in-place.

        Resolves all equipped item IDs to aegis names, finds active combos
        (all required items present), parses each combo script, and aggregates
        bonuses via the same _apply() path used for individual item scripts.

        Active combo labels are appended to bonuses.active_combo_descriptions.

        profile: ServerProfile (optional) — passed to DataLoader.get_active_combos()
                 to include PS-custom combos when server=payon_stories.

        script_ctx: player-side runtime context for conditional evaluation.
          Combo scripts use refine=0 (no per-slot refine for combo bonuses).
        """
        # Build aegis name set from all equipped item slots (ignore card slots — cards
        # are individual items already in equipped as {slot}_card_{i} keys).
        equipped_aegis: set[str] = set()
        for item_id in equipped.values():
            if item_id is None:
                continue
            item = loader.get_item(item_id)
            if item and item.get("aegis_name"):
                equipped_aegis.add(item["aegis_name"])

        if not equipped_aegis:
            return

        active = loader.get_active_combos(frozenset(equipped_aegis), profile=profile)
        for combo in active:
            effects = parse_script(combo["script"], script_ctx)
            for eff in effects:
                if eff.bonus_type == "skill":
                    _sk_name = str(eff.params[0])
                    _sk_lv   = eff.params[1] if isinstance(eff.params[1], int) else 1
                    bonuses.skill_grants[_sk_name] = max(
                        bonuses.skill_grants.get(_sk_name, 0), _sk_lv
                    )
                else:
                    GearBonusAggregator._apply(bonuses, eff)

            # Build a human-readable label: "Item A + Item B -> description, ..."
            item_labels = " + ".join(
                (loader.get_item_by_aegis(name) or {}).get("name", name)
                for name in combo["items"]
            )
            effect_descs = [
                _make_description(e.bonus_type, e.arity, e.params)
                for e in effects
                if not e.description.startswith("[")  # skip unknown bonuses
            ]
            if effect_descs:
                bonuses.active_combo_descriptions.append(
                    f"{item_labels}: {', '.join(effect_descs)}"
                )
