from core.models.target import Target
from core.models.damage import DamageResult
from core.models.build import PlayerBuild
from core.models.gear_bonuses import GearBonuses
from core.models.skill import SkillInstance
from core.config import BattleConfig
from pmf.operations import _scale_floor, _subtract_uniform, _floor_at, pmf_stats

# G68: element int → Ele_* string key for pdef=1 lookup
_ELE_INT_TO_KEY: list[str] = [
    "Ele_Neutral", "Ele_Water", "Ele_Earth", "Ele_Fire",
    "Ele_Wind", "Ele_Poison", "Ele_Holy", "Ele_Dark", "Ele_Ghost", "Ele_Undead",
]

_RACE_TO_RC = {
    "Formless":  "RC_Formless",
    "Undead":    "RC_Undead",
    "Brute":     "RC_Brute",
    "Plant":     "RC_Plant",
    "Insect":    "RC_Insect",
    "Fish":      "RC_Fish",
    "Demon":     "RC_Demon",
    "Demi-Human": "RC_DemiHuman",
    "Angel":     "RC_Angel",
    "Dragon":    "RC_Dragon",
}


class DefenseFix:
    """Exact pre-renewal defense reduction for BF_WEAPON attacks.
    Hard DEF percentage applied first, then soft VIT DEF subtracted.
    Both hard DEF (percentage) and soft DEF (VIT) carry their own variance:
      - Hard DEF is deterministic (percentage of current damage).
      - Soft DEF has a random range; independent of weapon ATK variance so the
        subtraction is crossed: min output = min weapon dmg - max VIT DEF,
        max output = max weapon dmg - min VIT DEF.
    Source: battle.c battle_calc_defense, pre-renewal path (~line 1397)."""

    @staticmethod
    def calculate(target: Target, build: PlayerBuild, gear_bonuses: GearBonuses,
                  pmf: dict, config: BattleConfig, result: DamageResult,
                  is_crit: bool = False, skill: SkillInstance = None) -> dict:
        """VIT penalty applied to def1/def2 before reduction (exact source position).

        flag.idef sources (both cause calc_defense to be skipped entirely):
          - Crit (#ifndef RENEWAL): flag.idef = flag.idef2 = 1 (battle.c:4988-4989)
          - NK_IGNORE_DEF skill flag: flag.idef = flag.idef2 = 1 (battle.c:4673)
        Both result in (!flag.idef || !flag.idef2) = false → calc_defense not called.

        pdef sources (alter the formula inside calc_defense, pre-renewal #else block):
          - MO_INVESTIGATE: flag.pdef = flag.pdef2 = 2 (battle.c:4759)
            → damage = damage * 2 * (def1 + vit_def) / 100  (DEF amplifies instead of reduces)
          - def_ratio_atk_ele/race card bonuses: flag.pdef = 1 (battle.c:5686/5694)
            → damage = damage * 1 * (def1 + vit_def) / 100  (not yet implemented — needs gear_bonuses field)

        AM_ACIDTERROR: def1 forced to 0 before formula (#ifndef RENEWAL, battle.c:1474).
        """
        nk_ignore = skill.nk_ignore_def if skill is not None else False
        if is_crit or nk_ignore:
            if is_crit:
                reason = "crit sets flag.idef=flag.idef2=1 (#ifndef RENEWAL, battle.c:4988-4989)"
                src_ref = ("battle.c:4988-4989 (#ifndef RENEWAL):\n"
                           "flag.idef = flag.idef2 = flag.hit = 1;\n"
                           "Then: if((!flag.idef || !flag.idef2)) → false → calc_defense not called.")
            else:
                reason = "NK_IGNORE_DEF flag sets flag.idef=flag.idef2=1 (battle.c:4673)"
                src_ref = ("battle.c:4673: flag.idef = flag.idef2 = (nk&NK_IGNORE_DEF) ? 1 : 0;\n"
                           "Then: if((!flag.idef || !flag.idef2)) → false → calc_defense not called.")
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name="Defense Fix",
                value=av,
                min_value=mn,
                max_value=mx,
                multiplier=1.0,
                note=f"BYPASSED — {reason} (DEF {target.def_}, VIT {target.vit} readable but not applied)",
                formula="no change (defense skipped)",
                hercules_ref=src_ref,
            )
            return pmf

        def1 = max(0, min(100, target.def_))

        target_scs = target.target_active_scs
        if "SC_STONE" in target_scs or "SC_FREEZE" in target_scs:
            def1 = def1 >> 1  # status.c:5013-5016 #ifndef RENEWAL

        # G5/G225 ignore_def: partial DEF pierce by race (bIgnoreDefRate) or element (bIgnoreDefEle, PS-custom).
        # Applies to both hard DEF (def1) and soft VIT DEF (def2):
        #   battle.c:1441: def1 -= def1 * i / 100;
        #   battle.c:1444 (#ifndef RENEWAL): def2 -= def2 * i / 100;
        # battle.c:1440: if (i > 100) i = 100;  — capped before application.
        race_rc = _RACE_TO_RC.get(target.race, "")
        boss_rc = "RC_Boss" if target.is_boss else "RC_NonBoss"
        target_ele_key = (_ELE_INT_TO_KEY[target.element]
                          if 0 <= target.element < len(_ELE_INT_TO_KEY) else "")
        ignore_pct = (gear_bonuses.ignore_def_rate.get(race_rc, 0)
                      + gear_bonuses.ignore_def_rate.get(boss_rc, 0)
                      + gear_bonuses.ignore_def_ele.get(target_ele_key, 0))
        if getattr(build, "ignore_hard_def", False) or ignore_pct >= 100:
            def1 = 0
            note_def = "Hard DEF ignored (100%)"
        elif ignore_pct > 0:
            def1 = max(0, def1 * (100 - ignore_pct) // 100)
            note_def = f"Hard DEF {target.def_} → {def1} (−{ignore_pct}% ignored)"
        else:
            note_def = f"Hard DEF {def1}"

        # AM_ACIDTERROR: armor DEF forced to 0 in pre-renewal — only vit_def (soft DEF) applies.
        # battle.c:1474 (#ifndef RENEWAL): if (skill_id == AM_ACIDTERROR) def1 = 0;
        if skill is not None and skill.name == "AM_ACIDTERROR":
            def1 = 0
            note_def = f"Hard DEF forced 0 (AM_ACIDTERROR, battle.c:1474 #ifndef RENEWAL)"

        def2 = max(1, target.vit)

        if "SC_ETERNALCHAOS" in target_scs:
            def2 = 0  # status.c:5090: returns 0 from status_calc_def2

        # VIT penalty (full mechanic – uses target.targeted_count, respects bitmask)
        if config.vit_penalty_type != 0 and (config.vit_penalty_target & (1 if target.is_pc else 2)) != 0:
            target_count = target.targeted_count
            if target_count >= config.vit_penalty_count:
                if getattr(target, 'active_status_levels', {}).get("SC_STEELBODY", 0) == 0:
                    penalty = (target_count - (config.vit_penalty_count - 1)) * config.vit_penalty_num
                    if config.vit_penalty_type == 1:
                        def1 = def1 * (100 - penalty) // 100
                        def2 = def2 * (100 - penalty) // 100
                    else:
                        def1 -= penalty
                        def2 -= penalty

        # G5/G225 ignore_def: apply same percentage to soft VIT DEF (def2).
        # battle.c:1444 (#ifndef RENEWAL): def2 -= def2 * i / 100
        # ignore_pct already capped implicitly (>=100 path zeroed def1 above; here we re-cap for safety).
        if ignore_pct > 0:
            _eff_ignore = 100 if (getattr(build, "ignore_hard_def", False) or ignore_pct >= 100) else ignore_pct
            def2 = max(0, def2 - def2 * _eff_ignore // 100)

        is_pdef2 = (skill is not None and skill.name == "MO_INVESTIGATE")

        # G68: pdef=1 — def_ratio_atk_ele/race card bonuses trigger DEF-as-multiplier formula.
        # battle.c:5686/5694: if (def_ratio_atk_ele & (1<<def_ele) || def_ratio_atk_race & race_mask)
        #   flag.pdef = 1  →  damage = damage * 1 * (def1 + vit_def) / 100
        # Skipped if is_crit (already returned early) or NK_IGNORE_DEF (already returned early).
        # target_ele_key/race_rc/boss_rc already computed above in the ignore_pct block.
        is_pdef1 = (not is_pdef2) and (
            gear_bonuses.def_ratio_atk_ele.get(target_ele_key, 0) > 0
            or gear_bonuses.def_ratio_atk_race.get(race_rc, 0) > 0
            or gear_bonuses.def_ratio_atk_race.get(boss_rc, 0) > 0
            or gear_bonuses.def_ratio_atk_race.get("RC_All", 0) > 0
        )

        # Soft VIT DEF range computation (needed for both normal and pdef=2 paths).
        # _subtract_uniform convolves the PMF with the negated uniform for exact crossing.
        if target.is_pc:
            # battle.c: vit_def = def2*(def2-15)/150;
            # battle.c: vit_def = def2/2 + (vit_def>0 ? rnd()%vit_def : 0);
            # rnd()%n gives [0, n-1], so range is [def2/2, def2/2 + variance_max-1]
            variance_max = def2 * (def2 - 15) // 150
            vd_min = def2 // 2
            vd_max = def2 // 2 + (variance_max - 1 if variance_max > 0 else 0)
            # avg of rnd()%n is (n-1)/2; n//2 rounds half-up (C1a fix)
            vd_avg = def2 // 2 + (variance_max // 2 if variance_max > 0 else 0)
            # SC_ANGELUS: vit_def *= def_percent/100 (battle.c:1492, pre-renewal PC path only)
            # Hard DEF (def1) is NOT scaled for PCs in pre-renewal (only mob/pet targets).
            # SC_PROVOKE effect is already in target.def_percent (StatusCalculator for player
            # targets, apply_mob_scs for mob targets) — no separate prov_lv needed here.
            dp = getattr(target, "def_percent", 100)
            if dp != 100:
                vd_min = vd_min * dp // 100
                vd_max = vd_max * dp // 100
                vd_avg = vd_avg * dp // 100
            note_type = "PC"
        else:
            # battle.c: vit_def = (def2/20)*(def2/20);
            # battle.c: vit_def = def2 + (vit_def>0 ? rnd()%vit_def : 0);
            # rnd()%n gives [0, n-1], so range is [def2, def2 + variance_max-1]
            variance_max = (def2 // 20) * (def2 // 20)
            vd_min = def2
            vd_max = def2 + (variance_max - 1 if variance_max > 0 else 0)
            # avg of rnd()%n is (n-1)/2; n//2 rounds half-up (C1a fix)
            vd_avg = def2 + (variance_max // 2 if variance_max > 0 else 0)
            # def_percent scales both def1 and vit_def for mob/pet targets (battle.c:1508-1509).
            # PC path (above) scales vit_def only (battle.c:1492).
            mob_dp = target.def_percent
            if mob_dp != 100:
                def1 = def1 * mob_dp // 100
                vd_min = vd_min * mob_dp // 100
                vd_max = vd_max * mob_dp // 100
                vd_avg = vd_avg * mob_dp // 100
            note_type = "monster"

        if is_pdef2:
            # MO_INVESTIGATE — flag.pdef = flag.pdef2 = 2 (battle.c:4759)
            # Pre-renewal formula (battle.c:1539 #else):
            #   damage = damage * pdef * (def1 + vit_def) / 100;  (pdef=2)
            #   vit_def NOT subtracted separately (flag&2 blocks the subtract)
            # DEF reversal: higher DEF → higher damage. vit_def is random; avg used for PMF.
            factor_lo = 2 * (def1 + vd_min)
            factor_hi = 2 * (def1 + vd_max)
            factor_avg = 2 * (def1 + vd_avg)
            pmf = _scale_floor(pmf, factor_avg, 100)
            pmf = _floor_at(pmf, 1)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name="Defense Fix",
                value=av,
                min_value=mn,
                max_value=mx,
                multiplier=factor_avg / 100.0,
                note=(f"MO_INVESTIGATE pdef=2: {note_def} + vit_def [{vd_min},{vd_max}] avg {vd_avg} ({note_type})"
                      f" — multiplier range [{factor_lo/100:.2f}×, {factor_hi/100:.2f}×] avg {factor_avg/100:.2f}×"
                      f" (PMF uses avg; higher DEF = more damage)"),
                formula=f"dmg * 2 * (def1 + vit_def) / 100  [factor {factor_lo/100:.2f}–{factor_hi/100:.2f}×]",
                hercules_ref="battle.c:4759: flag.pdef = flag.pdef2 = 2; (MO_INVESTIGATE)\n"
                             "battle.c:1539 (#else pre-re): if(flag&2) damage = damage * pdef * (def1+vit_def) / 100;\n"
                             "battle.c:1542 (#else pre-re): if(!(flag&1 || flag&2)) damage -= vit_def;  ← skipped for pdef=2",
            )
        elif is_pdef1:
            # G68: def_ratio_atk_ele/race card bonus — flag.pdef = 1 (battle.c:5686/5694)
            # Pre-renewal formula (battle.c:1539 #else):
            #   damage = damage * 1 * (def1 + vit_def) / 100;
            #   vit_def NOT subtracted separately (flag&2 blocks the subtract)
            # Unlike pdef=2, higher DEF still reduces damage (factor typically < 100%).
            factor_lo = def1 + vd_min
            factor_hi = def1 + vd_max
            factor_avg = def1 + vd_avg
            pmf = _scale_floor(pmf, factor_avg, 100)
            pmf = _floor_at(pmf, 1)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name="Defense Fix",
                value=av,
                min_value=mn,
                max_value=mx,
                multiplier=factor_avg / 100.0,
                note=(f"pdef=1 (def_ratio card): {note_def} + vit_def [{vd_min},{vd_max}] avg {vd_avg} ({note_type})"
                      f" — multiplier range [{factor_lo/100:.2f}×, {factor_hi/100:.2f}×] avg {factor_avg/100:.2f}×"),
                formula=f"dmg * (def1 + vit_def) / 100  [factor {factor_lo/100:.2f}–{factor_hi/100:.2f}×]",
                hercules_ref="battle.c:5686/5694: def_ratio_atk_ele/race → flag.pdef=1\n"
                             "battle.c:1539 (#else pre-re): if(flag&2) damage = damage * pdef * (def1+vit_def) / 100;\n"
                             "battle.c:1542 (#else pre-re): if(!(flag&1 || flag&2)) damage -= vit_def;  ← skipped for pdef=1",
            )
        else:
            # Normal pre-renewal defense reduction.
            # Hard DEF: deterministic percentage — applies uniformly to the PMF.
            # battle.c: damage = damage * (100-def1) / 100;
            pmf = _scale_floor(pmf, 100 - def1, 100)
            # Soft VIT DEF: random range — independent of weapon ATK variance.
            pmf = _subtract_uniform(pmf, vd_min, vd_max)
            pmf = _floor_at(pmf, 1)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name="Defense Fix",
                value=av,
                min_value=mn,
                max_value=mx,
                multiplier=1.0,
                note=f"{note_def} → ×{(100-def1)/100:.0%} + Soft DEF [{vd_min},{vd_max}] avg {vd_avg} ({note_type})",
                formula=f"max(1, dmg * (100 - def1) // 100 - vit_def_range [{vd_min},{vd_max}])",
                hercules_ref="battle.c: defType def1 = status_get_def(target); short def2 = tstatus->def2, vit_def;\n"
                             "battle.c: if (def1 > 100) def1 = 100;\n"
                             "battle.c: damage = damage * (100-def1) / 100;\n"
                             "battle.c: if (!(flag & 1 || flag & 2)) damage -= vit_def;\n"
                             "battle.c: if (tsd) { vit_def = def2*(def2-15)/150; vit_def = def2/2 + (vit_def>0 ? rnd()%vit_def : 0); }\n"
                             "battle.c: else { vit_def = (def2/20)*(def2/20); vit_def = def2 + (vit_def>0 ? rnd()%vit_def : 0); }"
            )
        return pmf

    @staticmethod
    def calculate_magic(target: Target, gear_bonuses: GearBonuses,
                        pmf: dict, result: DamageResult,
                        mdef_ignore_pct: int = 0) -> dict:
        """BF_MAGIC defense reduction (pre-renewal, magic_defense_type=0).

        Formula: damage = damage * (100 - mdef) / 100 - mdef2
        ignore_mdef: sd->ignore_mdef[race] + ignore_mdef[boss/nonboss] reduces mdef%.
        mdef_ignore_pct: additional % MDEF reduction (e.g. 50 for PS Soul Strike lv10 learned).
        Source: battle.c:1549-1592 BF_MAGIC case (#else not RENEWAL, magic_defense_type=0).
        """
        mdef = max(0, min(100, target.mdef_))
        if target.mdef_percent != 100:
            mdef = max(0, min(100, mdef * target.mdef_percent // 100))
        if "SC_STONE" in target.target_active_scs or "SC_FREEZE" in target.target_active_scs:
            mdef = min(100, mdef + 25 * mdef // 100)  # status.c:5153-5156
        # Soft MDEF: int_ + vit//2 (status.c:3867 #else not RENEWAL)
        mdef2 = target.int_ + (target.vit >> 1)

        # ignore_mdef: reduce mdef by percentage (same pattern as ignore_def_rate)
        # battle.c:1566-1572: i = sd->ignore_mdef[boss/nonboss] + ignore_mdef[race]
        race_rc = _RACE_TO_RC.get(target.race, "")
        boss_rc = "RC_Boss" if target.is_boss else "RC_NonBoss"
        ignore_pct = (gear_bonuses.ignore_mdef_rate.get(race_rc, 0)
                      + gear_bonuses.ignore_mdef_rate.get(boss_rc, 0))
        if ignore_pct > 0:
            ignore_pct = min(100, ignore_pct)
            mdef = max(0, mdef - mdef * ignore_pct // 100)
            note_ignore = f" (−{ignore_pct}% ignored → {mdef})"
        else:
            note_ignore = ""

        # PS Soul Strike lv10 learned: 50% MDEF reduction (skill parameter toggle).
        # JSONL: "ignores 50% of the target's MDEF regardless of the current Soul Strike level".
        if mdef_ignore_pct > 0:
            mdef = max(0, mdef - mdef * mdef_ignore_pct // 100)
            note_ignore += f" (PS Soul Strike lv10: −{mdef_ignore_pct}% MDEF → {mdef})"

        # battle.c:1585 #else not RENEWAL, magic_defense_type=0:
        # damage = damage * (100 - mdef) / 100 - mdef2
        pmf = _scale_floor(pmf, 100 - mdef, 100)
        pmf = _subtract_uniform(pmf, mdef2, mdef2)
        pmf = _floor_at(pmf, 1)

        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            name="Magic Defense Fix",
            value=av,
            min_value=mn,
            max_value=mx,
            multiplier=1.0,
            note=f"MDEF {target.mdef_}{note_ignore} → ×{(100-mdef)/100:.0%} − mdef2 {mdef2}",
            formula=f"max(1, dmg * (100 - mdef) // 100 - mdef2)",
            hercules_ref="battle.c:1585 (#else not RENEWAL, magic_defense_type=0):\n"
                         "damage = damage * (100-mdef)/100 - mdef2;"
        )
        return pmf
