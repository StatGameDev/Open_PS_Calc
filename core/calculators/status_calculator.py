"""
StatusCalculator — computes all derived player stats from a PlayerBuild.

Input:  PlayerBuild, Weapon, GearBonuses (populated by GearBonusAggregator)
Output: StatusData — BATK, HIT, FLEE, CRI, ASPD, MaxHP, MaxSP, MATK, MDEF, DEF, regen

Called by PlayerStateBuilder (player_state_builder.py) before the damage pipeline runs.
Pre-renewal port of status_calc_pc_ + status_calc_misc (status.c).
SC stat modifiers follow status_calc_bl_ ordering: applied after the MaxHP/MaxSP base snapshot.
"""
from core.build_manager import effective_is_ranged
from core.config import BattleConfig
from core.data_loader import loader
from core.models.build import PlayerBuild
from core.models.gear_bonuses import GearBonuses
from core.models.status import StatusData
from core.models.weapon import Weapon
from core.server_profiles import get_profile

_GUN_WEAPON_TYPES    = frozenset({"Revolver", "Rifle", "Gatling", "Shotgun", "Grenade"})
_ADRENALINE_WEAPONS  = frozenset({"1HAxe", "2HAxe", "Mace"})
# skill_db.conf: BS_ADRENALINE2 and SC_ASSNCROS exclude bows and all gun types
_BOW_GUN_WEAPONS     = frozenset({"Bow", "Revolver", "Rifle", "Gatling", "Shotgun", "Grenade"})
_TF_MISS_JOBL2 = frozenset({12, 17, 4013, 4018})  # 2nd-class thief jobs (Assassin, Rogue + trans)


class StatusCalculator:
    def __init__(self, config: BattleConfig):
        self.config = config

    def calculate(self, build: PlayerBuild, weapon: Weapon, gb: GearBonuses | None = None) -> StatusData:
        status = StatusData()
        profile = get_profile(build.server)
        # gb.effective_mastery — mastery-skill levels from items/cards, set by GearBonusAggregator (gear_bonus_aggregator.py)
        mastery = gb.effective_mastery if gb is not None else build.mastery_levels

        # Job stat bonuses — vanilla from job_db2.txt; PS overrides via ps_job_bonuses.
        # Source: Hercules/db/job_db2.txt; pc.c:2489 param_bonus[type-SP_STR]+=val
        _ps_jb = profile.ps_job_bonuses.get(build.job_id)
        if _ps_jb is not None:
            jb = {"str_": 0, "agi": 0, "vit": 0, "int_": 0, "dex": 0, "luk": 0}
            for (lv, stat) in _ps_jb:
                if lv <= build.job_level:
                    jb[stat] += 1
        else:
            jb = loader.get_job_bonus_stats(build.job_id, build.job_level)

        # Total stats (base + job bonus + equipment/cards/buffs)
        status.str = build.base_str + build.bonus_str + jb["str_"]
        status.agi = build.base_agi + build.bonus_agi + jb["agi"]
        status.vit = build.base_vit + build.bonus_vit + jb["vit"]
        status.int_ = build.base_int + build.bonus_int + jb["int_"]
        status.dex = build.base_dex + build.bonus_dex + jb["dex"]
        status.luk = build.base_luk + build.bonus_luk + jb["luk"]

        support = build.support_buffs
        active_sc = build.active_status_levels

        # === PASSIVE SKILL STAT BONUSES ===
        # These are part of bstatus in Hercules (status_calc_pc_, status.c:1881-1889) —
        # computed before SC effects and included in the max_hp/max_sp base.

        # BS_HILTBINDING: STR +1 (status.c:1881)
        if mastery.get("BS_HILTBINDING", 0):
            status.str += 1

        # SA_DRAGONOLOGY: INT += (lv+1)//2 (status.c:1882)
        _sa_dragonology_lv = mastery.get("SA_DRAGONOLOGY", 0)
        if _sa_dragonology_lv:
            status.int_ += (_sa_dragonology_lv + 1) // 2

        # AC_OWL: DEX += lv (status.c:1884)
        _ac_owl_lv = mastery.get("AC_OWL", 0)
        if _ac_owl_lv:
            status.dex += _ac_owl_lv

        # === BASE-STATUS SNAPSHOT FOR MAX HP / MAX SP ===
        # Hercules computes max_hp and max_sp in status_calc_pc_ using bstatus (base + job +
        # equipment + passive skills only). SC effects are applied later in status_calc_bl_ and
        # do NOT influence max_hp/max_sp. Snapshot here mirrors that split so any future SC that
        # adds INT or VIT won't silently inflate max_sp or max_hp.
        # Source: status.c:1325 (status_get_base_maxsp uses bstatus->int_),
        #         status.c:1346 (status_get_base_maxhp uses bstatus->vit),
        #         status.c:1898-1950 (bstatus built before max_sp calc)
        _int_for_maxsp = status.int_
        _vit_for_maxhp = status.vit

        # === SC STAT MODIFIERS (status_calc_bl_ — applied after snapshot) ===
        # These affect BATK, HIT, FLEE, ASPD, and display stats but NOT max_hp/max_sp.

        # SC_SHOUT (MC_LOUD lv1): str +4 flat, hardcoded — no level scaling
        # status.c:3956-3957
        if "SC_SHOUT" in active_sc:
            status.str += 4

        # SC_NJ_NEN (NJ_NEN): str += val1=lv, int_ += val1=lv (vanilla)
        # status.c:3962-3963 (str), 4148-4149 (int_); val1=skill_lv via sc_start (skill.c:7428)
        # PS override: +2×lv STR/INT via profile.passive_overrides["SC_NJ_NEN"].
        if "SC_NJ_NEN" in active_sc:
            _lv = active_sc["SC_NJ_NEN"]
            _nen_spec = profile.passive_overrides.get("SC_NJ_NEN", {})
            status.str  += _lv * _nen_spec.get("str_per_lv", 1)
            status.int_ += _lv * _nen_spec.get("int_per_lv", 1)

        # SC_CONCENTRATION (AC_CONCENTRATION — Attention Concentrate): agi/dex % boost
        # val2 = 2 + skill_lv (lv1=3%, lv10=12%). Blocked by SC_QUAGMIRE.
        # Amplifies base + job + gear/passive bonuses. Card-script bonuses (param_bonus[])
        # are excluded from the amplification base — Hercules subtracts val3/val4 (snapshotted
        # from param_bonus[1]/[4] at SC start) before multiplying.
        # Party buff flat additions (SC_INC_AGI, SC_BLESSING, SC_GS_ACCURACY) are applied
        # in the block below, after SC_CONCENTRATION, matching Hercules ordering.
        # Source: status.c:8281-8290 (init), 4007-4008 (agi), 4195-4196 (dex)
        if "SC_CONCENTRATION" in active_sc and "SC_QUAGMIRE" not in build.player_active_scs:
            _lv    = active_sc["SC_CONCENTRATION"]
            _val2  = 2 + _lv
            _cards = gb.from_cards if gb is not None else None
            status.agi += (status.agi - (_cards.agi if _cards else 0)) * _val2 // 100
            status.dex += (status.dex - (_cards.dex if _cards else 0)) * _val2 // 100

        # === PARTY BUFF SCs — FLAT STAT ADDITIONS ===
        # Applied after SC_CONCENTRATION to match Hercules status_calc_* ordering.
        # SC_BLESSING STR/INT have no SC_CONCENTRATION interaction but belong here —
        # Hercules applies them in status_calc_str/int_, not in the pre-calc bstatus phase.
        _blessing_lv = support.get("SC_BLESSING", 0)
        if _blessing_lv:
            # status.c:8271-8275, 4209-4214
            status.str  += _blessing_lv
            status.int_ += _blessing_lv
            status.dex  += _blessing_lv

        _inc_agi_lv = support.get("SC_INC_AGI", 0)
        if _inc_agi_lv:
            # SC_INC_AGI: agi += 2+lv (status.c:4021-4022)
            status.agi += 2 + _inc_agi_lv

        if support.get("SC_GLORIA"):
            # SC_GLORIA: luk += 30 (status.c:4273-4274)
            status.luk += 30

        # SC_GS_ACCURACY (GS_INCREASING): agi +4, dex +4 flat (status.c:4029, 4218)
        # hit +20 deferred to after HIT is calculated (status.c:4811)
        if "SC_GS_ACCURACY" in active_sc:
            status.agi += 4
            status.dex += 4

        # === PLAYER DEBUFFS (player_active_scs) ===
        # Applied before derived stats so BATK, HIT, FLEE, CRI pick up the penalties.
        player_scs = build.player_active_scs

        # SC_DECREASEAGI: agi -= 2+lv (status.c:7633, 4025-4026)
        if "SC_DECREASEAGI" in player_scs:
            status.agi -= 2 + player_scs["SC_DECREASEAGI"]

        # SC_CURSE: luk = 0 (status.c:4261)
        if "SC_CURSE" in player_scs:
            status.luk = 0

        # === BASE ATK ===
        # Ranged weapons (W_BOW etc.) swap STR/DEX roles in BATK.
        # is_ranged_override overrides; otherwise derived from weapon_type.
        str_val = status.str
        dex_val = status.dex
        if effective_is_ranged(build, weapon):
            str_val, dex_val = dex_val, str_val
        # status.c:3758–3772 status_base_atk (#else not RENEWAL)
        dstr = str_val // 10
        status.batk = str_val + (dstr * dstr) + (dex_val // 5) + (status.luk // 5)
        status.batk += build.bonus_batk

        # BS_HILTBINDING: #ifndef RENEWAL BATK +4 (status.c:1914)
        if mastery.get("BS_HILTBINDING", 0):
            status.batk += 4
            status.sources.setdefault("batk", {})["BS_HILTBINDING"] = 4

        # === SELF BUFF SC — BATK MODIFIERS ===
        # Both are #ifndef RENEWAL guards — pre-renewal only.

        # SC_GS_MADNESSCANCEL: batk += 100
        # status.c:4478-4479 (#ifndef RENEWAL)
        # In PS mode the flat BATK is replaced by the +30% rate bonus in ActiveStatusBonus.
        if "SC_GS_MADNESSCANCEL" in active_sc and "SC_GS_MADNESSCANCEL" not in profile.rate_bonuses:
            status.batk += 100
            status.sources.setdefault("batk", {})["SC_GS_MADNESSCANCEL"] = 100

        # SC_GS_GATLINGFEVER: batk += val3 = 20+10×lv
        # status.c:8351-8352 (#ifndef RENEWAL); val3 set in init block at status.c:8352
        # When profile has a rate_bonus for this SC, the flat BATK is replaced by that
        # rate bonus in ActiveStatusBonus — skip the flat add here.
        if "SC_GS_GATLINGFEVER" in active_sc and "SC_GS_GATLINGFEVER" not in profile.rate_bonuses:
            _lv = active_sc["SC_GS_GATLINGFEVER"]
            status.batk += 20 + 10 * _lv
            status.sources.setdefault("batk", {})["SC_GS_GATLINGFEVER"] = 20 + 10 * _lv

        # SC_CURSE: atk% -= 25 (status.c:4345-4346)
        if "SC_CURSE" in player_scs:
            status.batk = status.batk * 75 // 100

        # === DEFENSE ===
        status.def_ = build.equip_def                    # Hard DEF (def1) = equipment only
        status.def2 = status.vit + build.bonus_def2      # Soft DEF (vit_def) = VIT + bonuses

        # SC_ANGELUS: val2=5*level, pre-renewal (status.c:8320-8321, #ifndef RENEWAL at line 4426)
        # Multiplies computed vit_def for PC targets: vit_def *= def_percent/100 (battle.c:1492)
        # Hard DEF (def1) is NOT scaled for PC targets in pre-renewal (only for mob/pet targets).
        angelus_lv = int(support.get("SC_ANGELUS", 0))
        status.def_percent = 100 + 5 * angelus_lv

        # SC_POISON: def_percent -= 25 (status.c:4431-4432, no guard)
        # PS: increased penalty — def_percent -= 50.
        if "SC_POISON" in player_scs:
            _poison_def_penalty = 50 if build.server == "payon_stories" else 25
            status.def_percent = max(0, status.def_percent - _poison_def_penalty)

        # SC_PROVOKE: def_percent -= 5+5*lv (status.c:4401-4402)
        if "SC_PROVOKE" in player_scs:
            status.def_percent = max(0, status.def_percent - (5 + 5 * int(player_scs["SC_PROVOKE"])))

        # SC_FLING: val2 = 5*coins → def_percent -= val2 (status.c:8356-8357, status.c:4422-4423).
        if "SC_FLING" in player_scs:
            status.def_percent = max(0, status.def_percent - 5 * int(player_scs["SC_FLING"]))

        # Scale def2 for display (def2 is display-only; DefenseFix uses target.vit directly).
        if status.def_percent != 100:
            status.def2 = status.def2 * status.def_percent // 100

        # SC_ETERNALCHAOS: VIT DEF → 0 (status.c:5090: status_calc_def2 returns 0)
        if "SC_ETERNALCHAOS" in player_scs:
            status.def2 = 0

        # AL_DP: vit_def += lv*(3 + (base_level+1)*4//100) vs Demon/Undead mob (battle.c:1494)
        _al_dp_lv = mastery.get("AL_DP", 0)
        if _al_dp_lv and build.target_mob_id:
            _al_mob = loader.get_monster(build.target_mob_id)
            if _al_mob and _al_mob.race in ("Demon", "Undead"):
                status.def2 += _al_dp_lv * (3 + (build.base_level + 1) * 4 // 100)

        # SC_STEELBODY DEF override — must be last in DEF block (overrides all other DEF values).
        # Vanilla: returns 90 flat (status.c:4993 #ifndef RENEWAL).
        # PS formula via profile.steelbody_override[0] (def_fn).
        if "SC_STEELBODY" in active_sc:
            if profile.steelbody_override is not None:
                status.def_ = profile.steelbody_override[0](build.equip_def)
            else:
                status.def_ = 90

        # === CRITICAL ===
        # status.c:3876 — cri in 0.1% units: base 1.0% (=10) + 0.333% per LUK
        # Katar doubling (cri <<= 1) belongs in the crit roll (crit_chance.py),
        # NOT here, under the default Hercules config (show_katar_crit_bonus = 0).
        # When show_katar_crit_bonus = 1, status.c doubles cri here instead, but
        # that is the non-default path. We implement the default only.
        status.cri = 10 + (status.luk * 10 // 3) + (build.bonus_cri * 10)

        # SC_EXPLOSIONSPIRITS (MO_EXPLOSIONSPIRITS): cri += val2 = 75+25×lv
        # status.c:7844 (init: val2=75+25*val1), 4753-4754 (application)
        # Units: same 0.1% scale as status.cri (lv1=+10.0%, lv5=+35.0%)
        if "SC_EXPLOSIONSPIRITS" in active_sc:
            _lv = active_sc["SC_EXPLOSIONSPIRITS"]
            status.cri += 75 + 25 * _lv
            status.sources.setdefault("cri", {})["SC_EXPLOSIONSPIRITS"] = 75 + 25 * _lv

        # Passive CRI additions at max level (profile-driven).
        _as_katar_spec = profile.passive_overrides.get("AS_KATAR", {})
        if weapon.weapon_type == "Katar" and mastery.get("AS_KATAR", 0) >= 10:
            _katar_cri = _as_katar_spec.get("cri_at_max_lv", 0)
            status.cri += _katar_cri
            if _katar_cri:
                status.sources.setdefault("cri", {})["AS_KATAR"] = _katar_cri
        _dc_lesson_spec = profile.passive_overrides.get("DC_DANCINGLESSON", {})
        if mastery.get("DC_DANCINGLESSON", 0) >= 10:
            _dc_lesson_cri = _dc_lesson_spec.get("cri_at_max_lv", 0)
            status.cri += _dc_lesson_cri
            if _dc_lesson_cri:
                status.sources.setdefault("cri", {})["DC_DANCINGLESSON"] = _dc_lesson_cri

        # === HIT / FLEE ===
        # status.c:3864–3865 status_calc_misc (#else not RENEWAL)
        status.hit = build.base_level + status.dex + build.bonus_hit
        status.flee = build.base_level + status.agi + build.bonus_flee
        # status.c:3881 status_calc_misc
        status.flee2 = (status.luk + 10 + build.bonus_flee2) if self.config.enable_perfect_flee else 0

        # === SELF BUFF SC — HIT / FLEE MODIFIERS ===

        # SC_GS_ACCURACY (GS_INCREASING): hit +20
        # status.c:4811 (applied after base HIT derivation)
        if "SC_GS_ACCURACY" in active_sc:
            status.hit += 20
            status.sources.setdefault("hit", {})["SC_GS_ACCURACY"] = 20

        # SC_GS_ADJUSTMENT (GS_ADJUSTMENT): flee +30 both servers; hit −30 vanilla only.
        # status.c:4809 (hit), 4878 (flee). PS removes HIT penalty — ps_skill_db.json id=505.
        if "SC_GS_ADJUSTMENT" in active_sc:
            if "SC_GS_ADJUSTMENT_SKIP_HIT_PENALTY" not in profile.mechanic_flags:
                status.hit -= 30
                status.sources.setdefault("hit", {})["SC_GS_ADJUSTMENT"] = -30
            status.flee += 30
            status.sources.setdefault("flee", {})["SC_GS_ADJUSTMENT"] = 30

        # SC_RG_CCONFINE_M (RG_CLOSECONFINE): flee +10
        # status.c:4874
        if "SC_RG_CCONFINE_M" in active_sc:
            status.flee += 10
            status.sources.setdefault("flee", {})["SC_RG_CCONFINE_M"] = 10

        # SC_GS_GATLINGFEVER: flee −= val4 = 5×lv (vanilla only; PS suppresses via sc_quicken)
        # status.c:8350 (init: val4=5*val1), 4883 (application)
        if "SC_GS_GATLINGFEVER" in active_sc:
            _lv = active_sc["SC_GS_GATLINGFEVER"]
            _gf_quicken = profile.aspd_buffs.get("SC_GS_GATLINGFEVER", {}).get("sc_quicken", {})
            if not _gf_quicken.get("flee_suppress"):
                status.flee -= 5 * _lv
                status.sources.setdefault("flee", {})["SC_GS_GATLINGFEVER"] = -5 * _lv

        # SC_VIOLENTGALE (SA_VIOLENTGALE): flat FLEE bonus while standing on Wind-element ground
        # val2 = skill_lv * 3; status.c:7786-7790 (init), status.c:4870-4871 (apply: flee += val2)
        # Pre-renewal (#ifndef RENEWAL): bonus = 0 if player's armor element is not Wind (vanilla).
        # PS: FLEE +3/8/15 at lv 1/2/3; armor element restriction removed.
        _PS_VG_FLEE = (3, 8, 15)
        if support.get("ground_effect") == "SC_VIOLENTGALE":
            vg_lv = int(support.get("ground_effect_lv", 1))
            if "GROUND_EFFECT_PS_VALUES" in profile.mechanic_flags:
                _vg_flee = _PS_VG_FLEE[min(vg_lv, len(_PS_VG_FLEE)) - 1]
            else:
                _vg_flee = vg_lv * 3
            status.flee += _vg_flee
            status.sources.setdefault("flee", {})["SC_VIOLENTGALE"] = _vg_flee

        # Active SC FLEE/CRI additions (profile-driven).
        # Vanilla TWOHANDQUICKEN/SPEARQUICKEN FLEE/CRI are #ifdef RENEWAL only; zero defaults here.
        _tq_spec = profile.passive_overrides.get("SC_TWOHANDQUICKEN", {})
        if "SC_TWOHANDQUICKEN" in active_sc:
            _lv = active_sc["SC_TWOHANDQUICKEN"]
            _tq_flee = _tq_spec.get("flee_per_lv", 0) * _lv
            _tq_cri  = _tq_spec.get("cri_per_lv", 0) * _lv
            status.flee += _tq_flee
            status.cri  += _tq_cri
            if _tq_flee:
                status.sources.setdefault("flee", {})["SC_TWOHANDQUICKEN"] = _tq_flee
            if _tq_cri:
                status.sources.setdefault("cri", {})["SC_TWOHANDQUICKEN"] = _tq_cri
        _sq_stat_spec = profile.passive_overrides.get("SC_SPEARQUICKEN", {})
        if "SC_SPEARQUICKEN" in active_sc:
            _lv = active_sc["SC_SPEARQUICKEN"]
            _sq_cri = _sq_stat_spec.get("cri_per_lv", 0) * _lv
            status.cri += _sq_cri
            if _sq_cri:
                status.sources.setdefault("cri", {})["SC_SPEARQUICKEN"] = _sq_cri

        # === PASSIVE SKILL HIT/FLEE BONUSES ===
        # status_calc_pc_ (status.c, no guard unless noted)

        # BS_WEAPONRESEARCH: #ifndef RENEWAL HIT += lv*2 (status.c:2035)
        _bs_wr_lv = mastery.get("BS_WEAPONRESEARCH", 0)
        if _bs_wr_lv:
            status.hit += _bs_wr_lv * 2
            status.sources.setdefault("hit", {})["BS_WEAPONRESEARCH"] = _bs_wr_lv * 2

        # AC_VULTURE: #ifndef RENEWAL HIT += lv (status.c:2039–2042; range bonus not tracked)
        _ac_vulture_lv = mastery.get("AC_VULTURE", 0)
        if _ac_vulture_lv:
            status.hit += _ac_vulture_lv
            status.sources.setdefault("hit", {})["AC_VULTURE"] = _ac_vulture_lv

        # GS_SINGLEACTION: HIT += 2*lv (gun types only) (status.c:2047); PS override via profile.
        _gs_sa_lv = mastery.get("GS_SINGLEACTION", 0)
        if _gs_sa_lv and weapon.weapon_type in _GUN_WEAPON_TYPES:
            _gs_sa_hit = profile.passive_overrides.get("GS_SINGLEACTION", {}).get("hit_per_lv", 2)
            status.hit += _gs_sa_hit * _gs_sa_lv
            status.sources.setdefault("hit", {})["GS_SINGLEACTION"] = _gs_sa_hit * _gs_sa_lv

        # GS_SNAKEEYE: HIT += lv (gun types only) (status.c:2049–2051; range bonus not tracked)
        _gs_se_lv = mastery.get("GS_SNAKEEYE", 0)
        if _gs_se_lv and weapon.weapon_type in _GUN_WEAPON_TYPES:
            status.hit += _gs_se_lv
            status.sources.setdefault("hit", {})["GS_SNAKEEYE"] = _gs_se_lv

        # TF_MISS: FLEE += lv*4 (JOBL_2 thief: Assassin/Rogue + trans), else lv*3 (status.c:2064)
        _tf_miss_lv = mastery.get("TF_MISS", 0)
        if _tf_miss_lv:
            _tf_flee = _tf_miss_lv * 4 if build.job_id in _TF_MISS_JOBL2 else _tf_miss_lv * 3
            status.flee += _tf_flee
            status.sources.setdefault("flee", {})["TF_MISS"] = _tf_flee

        # MO_DODGE: FLEE += (lv*3)>>1 (status.c:2066); PS override via profile (flee_per_lv).
        _mo_dodge_lv = mastery.get("MO_DODGE", 0)
        if _mo_dodge_lv:
            _mo_dodge_spec = profile.passive_overrides.get("MO_DODGE", {})
            if "flee_per_lv" in _mo_dodge_spec:
                _mo_flee = _mo_dodge_lv * _mo_dodge_spec["flee_per_lv"]
            else:
                _mo_flee = (_mo_dodge_lv * 3) >> 1  # vanilla: floor(1.5 * lv)
            status.flee += _mo_flee
            status.sources.setdefault("flee", {})["MO_DODGE"] = _mo_flee

        # Passive HIT/FLEE additions (profile-driven; vanilla has no bonus for these skills).
        _nj_tobi_lv = mastery.get("NJ_TOBIDOUGU", 0)
        if _nj_tobi_lv:
            _nj_tobi_hit = profile.passive_overrides.get("NJ_TOBIDOUGU", {}).get("hit_per_lv", 0) * _nj_tobi_lv
            status.hit += _nj_tobi_hit
            if _nj_tobi_hit:
                status.sources.setdefault("hit", {})["NJ_TOBIDOUGU"] = _nj_tobi_hit
        _sa_fc_lv = mastery.get("SA_FREECAST", 0)
        if _sa_fc_lv:
            _sa_fc_flee = profile.passive_overrides.get("SA_FREECAST", {}).get("flee_per_lv", 0) * _sa_fc_lv
            status.flee += _sa_fc_flee
            if _sa_fc_flee:
                status.sources.setdefault("flee", {})["SA_FREECAST"] = _sa_fc_flee

        # SC_BLIND: hit *= 0.75, flee *= 0.75 — applied last, after all additive bonuses
        # status.c:4817-4818 (hit), status.c:4902-4903 (flee)
        if "SC_BLIND" in player_scs:
            status.hit  = status.hit  * 75 // 100
            status.flee = status.flee * 75 // 100

        # SC_QUAGMIRE: agi -= val2, dex -= val2; val2=10*lv (status.c:4027-4028, 4211-4212)
        if "SC_QUAGMIRE" in player_scs:
            val2 = 10 * int(player_scs["SC_QUAGMIRE"])
            status.agi = max(0, status.agi - val2)
            status.dex = max(0, status.dex - val2)

        # SC_PS_HYPOTHERMIA: dex -= 10 (stacks with SC_QUAGMIRE; user-confirmed PS behaviour)
        if "SC_PS_HYPOTHERMIA" in player_scs:
            status.dex = max(0, status.dex - 10)

        # === ASPD ===
        # Pre-renewal formula (status.c status_base_amotion_pc, #else = not RENEWAL_ASPD):
        #   Single weapon: amotion = aspd_base[job][RH_type]
        #   Dual-wield:    amotion = (aspd_base[job][RH_type] + aspd_base[job][LH_type]) * 7 / 10
        #   Source: status.c:3699-3701 (#else, pre-renewal)
        #   amotion -= amotion * (4*agi + dex) / 1000
        #   amotion += bonus.aspd_add  (flat from bAspd)
        #   amotion += 500-100*KN_CAVALIERMASTERY if riding peco (#ifndef RENEWAL_ASPD)
        #   clamped to [pc_max_aspd, 2000] = [2000 - max_aspd*10, 2000]
        # Displayed ASPD = (2000 - amotion) / 10  (client conversion)
        _DUAL_WIELD_JOBS = frozenset({12, 4013})  # Assassin, Assassin Cross
        lh_item_id = build.equipped.get("left_hand") if build.job_id in _DUAL_WIELD_JOBS else None
        lh_item = loader.get_item(lh_item_id) if lh_item_id is not None else None
        lh_weapon_type = lh_item.get("weapon_type", "Unarmed") if lh_item else "Unarmed"
        if lh_weapon_type != "Unarmed":
            # Dual-wield: (RH base + LH base) * 7 / 10  (status.c:3700-3701 #else)
            rh_base = loader.get_aspd_base(build.job_id, weapon.weapon_type)
            lh_base = loader.get_aspd_base(build.job_id, lh_weapon_type)
            base_amotion = (rh_base + lh_base) * 7 // 10
        else:
            base_amotion = loader.get_aspd_base(build.job_id, weapon.weapon_type)
        amotion = base_amotion - base_amotion * (4 * status.agi + status.dex) // 1000
        amotion += build.bonus_aspd_add  # flat amotion reduction from bAspd item/card bonuses

        # SC ASPD buffs — status.c:5587-5685 status_calc_aspd_rate (no RENEWAL guard)
        # Scale: 1000 = 100%. aspd_rate < 1000 → faster; aspd_rate > 1000 → slower.
        # Quicken SCs compete for max pool (take-max, no stacking, lines 5597-5650).
        # MADNESSCANCEL is NOT in the max pool — separate additional −200 (lines 5656-5657).
        # STEELBODY/DEFENDER add slowdown via aspd_rate += N (lines 5670-5675).
        sc_aspd_max = 0

        # SC_ONEHANDQUICKEN: fixed val2 = 300 (status.c vanilla)
        if "SC_ONEHANDQUICKEN" in active_sc:
            sc_aspd_max = max(sc_aspd_max, 300)

        # SC_TWOHANDQUICKEN: val2 = 300 vanilla; profile may override per weapon type.
        if "SC_TWOHANDQUICKEN" in active_sc:
            _tq_quicken_spec = profile.aspd_buffs.get("SC_TWOHANDQUICKEN", {}).get("quicken")
            if _tq_quicken_spec:
                _fn = _tq_quicken_spec.get(weapon.weapon_type)
                if _fn:
                    sc_aspd_max = max(sc_aspd_max, _fn(active_sc["SC_TWOHANDQUICKEN"]))
            else:
                sc_aspd_max = max(sc_aspd_max, 300)

        # SC_ADRENALINE: val3 = 300 (self/BS) or 200 (party member) (status.c:7226-7232)
        # support_buffs stores the actual val3 directly (300 or 200).
        # Gate: status_change_start:7227 rejects if weapon not 1HAxe/2HAxe/Mace (skill_db.conf:3940-3944)
        adrenaline_val = int(support.get("SC_ADRENALINE", 0))
        if adrenaline_val and weapon.weapon_type in _ADRENALINE_WEAPONS:
            sc_aspd_max = max(sc_aspd_max, adrenaline_val)

        # SC_ADRENALINE2 (Advanced Adrenaline Rush): same val3 formula (300 self / 200 party).
        # Whitesmith-only Spirit skill. status.c:5614-5616 (max pool), 7232-7233 (val3).
        # Gate: status_change_start:7233 rejects bows and guns (skill_db.conf:14095-14113)
        adrenaline2_val = int(support.get("SC_ADRENALINE2", 0))
        if adrenaline2_val and weapon.weapon_type not in _BOW_GUN_WEAPONS:
            sc_aspd_max = max(sc_aspd_max, adrenaline2_val)

        # SC_SPEARQUICKEN: val2 = 200+10×lv (status.c:7822 #ifndef RENEWAL_ASPD)
        # Profile may override with weapon-type-dependent formula via aspd_buffs.
        if "SC_SPEARQUICKEN" in active_sc:
            spear_lv = active_sc["SC_SPEARQUICKEN"]
            _sq_quicken = profile.aspd_buffs.get("SC_SPEARQUICKEN", {}).get("quicken")
            if _sq_quicken:
                _fn = _sq_quicken.get(weapon.weapon_type)
                if _fn:
                    sc_aspd_max = max(sc_aspd_max, _fn(spear_lv))
            else:
                sc_aspd_max = max(sc_aspd_max, 200 + 10 * spear_lv)

        # SC_ASSNCROS (Assassin's Cross): val2 = (MusLesson/2 + 10 + song_lv + bard_agi/10) * 10
        # skill.c:13296-13307 #else (pre-renewal)
        # Gate: status_calc_aspd_rate:5638-5645 suppresses for bow/gun weapon types
        # song_state — bard/dancer song inputs, populated by buffs_section.py
        song = build.song_state
        if song.get("SC_ASSNCROS") and weapon.weapon_type not in _BOW_GUN_WEAPONS:
            song_lv   = int(song["SC_ASSNCROS"])
            mus_lv    = int(song.get("SC_ASSNCROS_lesson", 0))
            s_agi     = int(song.get("SC_ASSNCROS_agi", 1))
            val2 = (mus_lv // 2 + 10 + song_lv + s_agi // 10) * 10
            sc_aspd_max = max(sc_aspd_max, val2)

        # SC_GS_GATLINGFEVER: val2 = 20×lv in max pool (status_calc_aspd_rate:5626-5628)
        if "SC_GS_GATLINGFEVER" in active_sc:
            _lv = active_sc["SC_GS_GATLINGFEVER"]
            sc_aspd_max = max(sc_aspd_max, 20 * _lv)

        sc_aspd_rate = 1000 - sc_aspd_max

        # Additive aspd bonus (status.c:5540-5560 pre-renewal #else section).
        # GS_GATLINGFEVER: aspd_add += val1 = lv (bonus += val1, status.c:5545-5546)
        # GS_MADNESSCANCEL: quicken floor — aspd_add = max(20, aspd_add) (status.c:~5560 #else)
        aspd_add = 0
        if "SC_GS_GATLINGFEVER" in active_sc:
            aspd_add += active_sc["SC_GS_GATLINGFEVER"]  # val1 = lv
        if "SC_GS_MADNESSCANCEL" in active_sc and aspd_add < 20:
            aspd_add = 20  # quicken floor (status.c:~5560)
        sc_aspd_rate -= aspd_add

        # SC_GS_MADNESSCANCEL: separate additional −200, not in max pool
        # status_calc_aspd_rate:5656-5657 (else-if; only applies when SC_BERSERK inactive)
        if "SC_GS_MADNESSCANCEL" in active_sc:
            sc_aspd_rate -= 200

        # === ASPD SLOWDOWNS (status_calc_aspd_rate:5670-5685, no RENEWAL guard) ===

        # SC_STEELBODY: aspd_rate += 250 (status_calc_aspd_rate:5670-5671)
        if "SC_STEELBODY" in active_sc:
            sc_aspd_rate += 250

        # SC_DEFENDER: aspd_rate += val4 = 250-50×lv (status_calc_aspd_rate:5674-5675)
        # lv1→200, lv2→150, lv3→100, lv4→50, lv5→0
        if "SC_DEFENDER" in active_sc:
            _lv = active_sc["SC_DEFENDER"]
            sc_aspd_rate += 250 - 50 * _lv

        # SC_DONTFORGETME: aspd_rate += 10*val2 (status.c:5667)
        # val2 = caster_agi//10 + 3*lv + 5 (skill.c:13270 #else pre-renewal)
        if "SC_DONTFORGETME" in player_scs:
            _lv = int(player_scs["SC_DONTFORGETME"])
            _caster_agi = int(player_scs.get("SC_DONTFORGETME_agi", 0))  # auxiliary key set by player_debuffs_section.py
            _val2 = _caster_agi // 10 + 3 * _lv + 5
            sc_aspd_rate += 10 * _val2

        # SC_PS_HYPOTHERMIA: -20% ASPD → aspd_rate += 200 (scale: 1000 = normal)
        if "SC_PS_HYPOTHERMIA" in player_scs:
            sc_aspd_rate += 200

        # SA_ADVANCEDBOOK: #ifndef RENEWAL_ASPD aspd_rate -= 5*lv (W_BOOK only) (status.c:2116)
        # PS overrides with per-level table via passive_overrides["SA_ADVANCEDBOOK"]["aspd_pct_per_lv"].
        _sa_advbook_lv = mastery.get("SA_ADVANCEDBOOK", 0)
        if _sa_advbook_lv and weapon.weapon_type == "Book":
            _ab_aspd = profile.passive_overrides.get("SA_ADVANCEDBOOK", {}).get("aspd_pct_per_lv", 0)
            if isinstance(_ab_aspd, list):
                sc_aspd_rate -= _ab_aspd[_sa_advbook_lv - 1] * 10
            elif _ab_aspd:
                sc_aspd_rate -= _ab_aspd * _sa_advbook_lv * 10
            else:
                sc_aspd_rate -= 5 * _sa_advbook_lv  # vanilla

        # GS_SINGLEACTION: #ifndef RENEWAL_ASPD aspd_rate -= ((lv+1)//2)*10 (gun types only) (status.c:2120)
        if _gs_sa_lv and weapon.weapon_type in _GUN_WEAPON_TYPES:
            sc_aspd_rate -= ((_gs_sa_lv + 1) // 2) * 10

        # Per-level passive ASPD bonuses (profile-driven via passive_overrides["aspd_pct_per_lv"]).
        # MO_IRONHAND −1%/lv in PS. 1% faster = aspd_rate −= 10 per lv.
        # List values require weapon gating — handled by skill-specific blocks above; skip here.
        for _ap_key, _ap_spec in profile.passive_overrides.items():
            _ap_pct = _ap_spec.get("aspd_pct_per_lv", 0)
            if _ap_pct and not isinstance(_ap_pct, list):
                _ap_lv = mastery.get(_ap_key, 0)
                if _ap_lv:
                    sc_aspd_rate -= _ap_pct * _ap_lv * 10

        # Lv10 passive ASPD rate bonuses (profile-driven via aspd_buffs["lv10_rate"]).
        for _aspd_key, _aspd_spec in profile.aspd_buffs.items():
            _lv10_rate = _aspd_spec.get("lv10_rate")
            if not _lv10_rate:
                continue
            if mastery.get(_aspd_key, 0) >= 10:
                _delta = _lv10_rate.get(weapon.weapon_type, 0)
                if _delta:
                    sc_aspd_rate += _delta

        if sc_aspd_rate != 1000:
            amotion = amotion * sc_aspd_rate // 1000

        # bonus_aspd_percent: percentage aspd_rate bonus (e.g. 10 = 10% faster)
        # Implemented as aspd_rate modifier: amotion *= (1000 - pct*10) / 1000
        # populated from bAspd_rate item/card bonus scripts (item_script_parser.py)
        if build.bonus_aspd_percent:
            amotion = amotion * (1000 - build.bonus_aspd_percent * 10) // 1000
        if build.is_riding_peco:
            cav_lv = mastery.get("KN_CAVALIERMASTERY", 0)
            amotion += 500 - 100 * cav_lv  # status.c #ifndef RENEWAL_ASPD
        min_amotion = 2000 - self.config.max_aspd * 10
        amotion = max(min_amotion, min(2000, amotion))
        status.aspd = (2000 - amotion) / 10  # player-facing display value (float, e.g. 185.3)

        # === MAX HP ===
        # status_calc_pc_ MaxHP (pre-renewal):
        #   hp_base = HPTable[job_id][base_level - 1]
        #   max_hp  = hp_base * (100 + vit) // 100
        # Uses _vit_for_maxhp (pre-SC snapshot) — SC effects don't touch VIT currently
        # but snapshot is here so future VIT-buffing SCs don't silently inflate max_hp.
        hp_base = loader.get_hp_at_level(build.job_id, build.base_level)
        status.max_hp = hp_base * (100 + _vit_for_maxhp) // 100
        status.max_hp += build.bonus_maxhp

        # CR_TRUST: MaxHP += lv*200 (status.c:1927)
        _cr_trust_lv = mastery.get("CR_TRUST", 0)
        if _cr_trust_lv:
            status.max_hp += _cr_trust_lv * 200

        # bMaxHPrate: max_hp = APPLY_RATE(max_hp, hprate); hprate starts at 100, gear adds delta.
        # Applied after flat bonuses, before SC song/ground effects. (status.c:1936-1937)
        if build.bonus_maxhp_rate:
            status.max_hp = status.max_hp * (100 + build.bonus_maxhp_rate) // 100

        # Super Novice HP bonus — applied after standard HP calc (profile-driven).
        if build.job_id == 23:
            for _thresh, _bonus in profile.sn_hp_bonus.items():
                if build.base_level >= _thresh:
                    status.max_hp += _bonus

        # === MAX SP ===
        # Same pattern: SPTable[job_id][base_level - 1] * (100 + int_) // 100
        # Uses _int_for_maxsp (pre-SC snapshot) — SC_BLESSING and SC_NJ_NEN INT bonuses
        # are applied in status_calc_bl_ and must NOT inflate max_sp. (status.c:1325)
        sp_base = loader.get_sp_at_level(build.job_id, build.base_level)
        status.max_sp = sp_base * (100 + _int_for_maxsp) // 100
        status.max_sp += build.bonus_maxsp
        if build.bonus_maxsp_rate:
            status.max_sp = status.max_sp * (100 + build.bonus_maxsp_rate) // 100

        # Super Novice SP bonus — applied after standard SP calc (profile-driven).
        if build.job_id == 23:
            for _thresh, _bonus in profile.sn_sp_bonus.items():
                if build.base_level >= _thresh:
                    status.max_sp += _bonus

        # === MATK ===
        # status.c:3783-3792 #else not RENEWAL (status_base_matk_min / _max)
        status.matk_min = status.int_ + (status.int_ // 7) ** 2
        status.matk_max = status.int_ + (status.int_ // 5) ** 2

        # bMatkRate: matk *= matk_rate/100; matk_rate starts at 100, gear adds delta.
        # Applied after base MATK, before SC effects. (status.c:1995-1997)
        if build.bonus_matk_rate:
            _pct = 100 + build.bonus_matk_rate
            status.matk_min = status.matk_min * _pct // 100
            status.matk_max = status.matk_max * _pct // 100

        # SC_MINDBREAKER: matk_percent += 20*lv — boosts outgoing magic damage (status.c:4376-4377)
        if "SC_MINDBREAKER" in player_scs:
            lv = int(player_scs["SC_MINDBREAKER"])
            pct = 100 + 20 * lv
            status.matk_min = status.matk_min * pct // 100
            status.matk_max = status.matk_max * pct // 100

        # SC_VOLCANO PS: +2/4/6% MATK at lv 1/2/3 (no vanilla equivalent).
        _PS_VOL_MATK_PCT = (2, 4, 6)
        if ("GROUND_EFFECT_PS_VALUES" in profile.mechanic_flags
                and support.get("ground_effect") == "SC_VOLCANO"):
            vol_lv = int(support.get("ground_effect_lv", 1))
            pct = 100 + _PS_VOL_MATK_PCT[min(vol_lv, len(_PS_VOL_MATK_PCT)) - 1]
            status.matk_min = status.matk_min * pct // 100
            status.matk_max = status.matk_max * pct // 100

        # bonus_matk_flat: SC_PLUSMAGICPOWER (matk_item) + SC_MATKFOOD consumables — flat addend.
        # Applied after rate scaling and SC% effects (status.c:4635-4638).
        if build.bonus_matk_flat:
            status.matk_min += build.bonus_matk_flat
            status.matk_max += build.bonus_matk_flat

        # === MDEF ===
        # Hard MDEF (mdef): from bMdef item scripts, routed through equip_mdef on PlayerBuild
        status.mdef = build.equip_mdef
        # Soft MDEF (mdef2): int_ + vit//2  (status.c:3867 #else not RENEWAL)
        status.mdef2 = status.int_ + (status.vit >> 1)

        # SC_ENDURE (SM_ENDURE): mdef += val1 = skill_lv, when val4=0 (skill cast, not Eddga card)
        # status.c:5149-5150: mdef += (val4==0) ? val1 : 1
        # val1=skill_lv via sc_start; we always treat as skill cast (val4=0 path)
        if "SC_ENDURE" in active_sc:
            status.mdef += active_sc["SC_ENDURE"]
            status.sources.setdefault("mdef", {})["SC_ENDURE"] = active_sc["SC_ENDURE"]

        # SC_MINDBREAKER: mdef_percent -= 12*lv; matk_percent += 20*lv (status.c:4376,4453)
        if "SC_MINDBREAKER" in player_scs:
            lv = int(player_scs["SC_MINDBREAKER"])
            status.mdef = max(0, status.mdef * (100 - 12 * lv) // 100)

        # SC_STEELBODY MDEF override — must be last in MDEF block (overrides all other MDEF values).
        # Vanilla: returns 90 flat (status.c:5141 #ifndef RENEWAL).
        # PS formula via profile.steelbody_override[1] (mdef_fn).
        if "SC_STEELBODY" in active_sc:
            if profile.steelbody_override is not None:
                status.mdef = profile.steelbody_override[1](build.equip_mdef)
            else:
                status.mdef = 90

        # === BARD SONGS (song_state) ===
        # All formulas from skill.c skill_unitsetting (#else pre-renewal blocks).
        # val stored as sg->val1 in skill_unitsetting → becomes SC->val2 when applied.
        # Per-song keys: "{SC_KEY}_{stat}" for caster stat, "{SC_KEY}_lesson" for lesson level.

        # SC_WHISTLE: val2=FLEE bonus, val3=FLEE2 bonus (×10 scale in status.c)
        # skill.c:13245-13251; status.c:~4866 (flee), ~4952 (flee2)
        if song.get("SC_WHISTLE"):
            song_lv  = int(song["SC_WHISTLE"])
            mus_lv   = int(song.get("SC_WHISTLE_lesson", 0))
            s_agi    = int(song.get("SC_WHISTLE_agi", 1))
            s_luk    = int(song.get("SC_WHISTLE_luk", 1))
            _whistle_flee  = song_lv + s_agi // 10 + mus_lv
            _whistle_flee2 = ((song_lv + 1) // 2 + s_luk // 10 + mus_lv) * 10
            status.flee  += _whistle_flee
            status.flee2 += _whistle_flee2
            status.sources.setdefault("flee", {})["SC_WHISTLE"] = _whistle_flee
            if _whistle_flee2:
                status.sources.setdefault("flee2", {})["SC_WHISTLE"] = _whistle_flee2

        # SC_APPLEIDUN: maxhp += maxhp * val2 / 100
        # skill.c:13283-13286; status.c:5766-5767
        if song.get("SC_APPLEIDUN"):
            song_lv  = int(song["SC_APPLEIDUN"])
            mus_lv   = int(song.get("SC_APPLEIDUN_lesson", 0))
            s_vit    = int(song.get("SC_APPLEIDUN_vit", 1))
            val2 = 5 + 2 * song_lv + s_vit // 10 + mus_lv
            status.max_hp += status.max_hp * val2 // 100

        # SC_DELUGE (SA_DELUGE): maxhp% bonus while standing on Water-element ground
        # val2 = deluge_eff[skill_lv-1] = {5, 9, 12, 14, 15}%; status.c:7793-7799 (init), 5768-5769 (apply)
        # Pre-renewal (#ifndef RENEWAL): bonus = 0 if player armor element is not Water (vanilla).
        # simplified: PS server applies no MaxHP% bonus; SP/HP regen not modelled. Armor element check not enforced.
        _DELUGE_EFF = (5, 9, 12, 14, 15)
        if support.get("ground_effect") == "SC_DELUGE":
            if "GROUND_EFFECT_PS_VALUES" not in profile.mechanic_flags:
                del_lv = int(support.get("ground_effect_lv", 1))
                del_val2 = _DELUGE_EFF[del_lv - 1]
                status.max_hp += status.max_hp * del_val2 // 100

        # SC_POEMBRAGI: cast time % + after-cast delay % (display-only)
        # skill.c:13261-13267; applied in cast time / ACD checks, not simulated here.
        if song.get("SC_POEMBRAGI"):
            song_lv  = int(song["SC_POEMBRAGI"])
            mus_lv   = int(song.get("SC_POEMBRAGI_lesson", 0))
            s_dex    = int(song.get("SC_POEMBRAGI_dex", 1))
            s_int    = int(song.get("SC_POEMBRAGI_int", 1))
            status.cast_time_reduction_pct       = 3 * song_lv + s_dex // 10 + 2 * mus_lv
            status.after_cast_delay_reduction_pct = (
                (3 * song_lv if song_lv < 10 else 50) + s_int // 5 + 2 * mus_lv
            )

        # SC_PS_HYPOTHERMIA: +20% cast time (players only; separate multiplicative step
        # in skill_timing.py, mirrors SC_SLOWCAST pattern in skill_castfix_sc:17242)
        if "SC_PS_HYPOTHERMIA" in player_scs:
            status.cast_time_penalty_pct += 20

        # === DANCER DANCES (song_state) ===

        # SC_HUMMING: hit += val2
        # skill.c:13253-13260; status.c:~4803-4804
        if song.get("SC_HUMMING"):
            song_lv   = int(song["SC_HUMMING"])
            dance_lv  = int(song.get("SC_HUMMING_lesson", 0))
            s_dex     = int(song.get("SC_HUMMING_dex", 1))
            _humming_hit = 2 * song_lv + s_dex // 10 + dance_lv
            status.hit += _humming_hit
            status.sources.setdefault("hit", {})["SC_HUMMING"] = _humming_hit

        # SC_FORTUNE: critical += val2 (10× scale — same units as rest of cri)
        # skill.c:13309-13313; status.c:~4755-4756
        if song.get("SC_FORTUNE"):
            song_lv   = int(song["SC_FORTUNE"])
            dance_lv  = int(song.get("SC_FORTUNE_lesson", 0))
            s_luk     = int(song.get("SC_FORTUNE_luk", 1))
            _fortune_cri = (10 + song_lv + s_luk // 10 + dance_lv) * 10
            status.cri += _fortune_cri
            status.sources.setdefault("cri", {})["SC_FORTUNE"] = _fortune_cri

        # SC_SERVICEFORYU: maxsp % + sp_cost_reduction_pct (display-only)
        # skill.c:13288-13294; status.c:~5847-5848
        if song.get("SC_SERVICEFORYU"):
            song_lv   = int(song["SC_SERVICEFORYU"])
            dance_lv  = int(song.get("SC_SERVICEFORYU_lesson", 0))
            s_int     = int(song.get("SC_SERVICEFORYU_int", 1))
            val2 = 15 + song_lv + s_int // 10 + dance_lv // 2
            val3 = 20 + 3 * song_lv + s_int // 10 + dance_lv // 2
            status.max_sp            += status.max_sp * val2 // 100
            status.sp_cost_reduction_pct = val3

        # === ENSEMBLES (song_state) ===

        # SC_DRUMBATTLE DEF bonus: def += val3 = (skill_lv+1)*2
        # status.c:4999-5000 (hard DEF, same block as equipment DEF)
        drum_lv = int(song.get("SC_DRUMBATTLE", 0))
        if drum_lv:
            _drum_def = (drum_lv + 1) * 2
            status.def_ += _drum_def
            status.sources.setdefault("def", {})["SC_DRUMBATTLE"] = _drum_def

        # SC_NIBELUNGEN has no stat effect beyond WATK (handled in base_damage.py).
        # SC_SIEGFRIED elemental resistance is applied in incoming_physical_pipeline.py.

        # === NATURAL TICK REGEN ===
        # status_calc_regen_pc (status.c:2650–2653, no RENEWAL guard)
        # regen->hp = 1 + (vit / 5) + (max_hp / 200)
        # regen->sp = 1 + (int_ / 6) + (max_sp / 100)
        # if int_ >= 120: sp += ((int_ - 120) / 2) + 4
        status.hp_regen = 1 + (status.vit // 5) + (status.max_hp // 200)
        status.sp_regen = 1 + (status.int_ // 6) + (status.max_sp // 100)
        if status.int_ >= 120:
            status.sp_regen += ((status.int_ - 120) // 2) + 4

        # === PASSIVE SKILL REGEN BONUSES ===
        # status_calc_regen_pc (status.c — no RENEWAL guard)

        # SM_RECOVERY: hp_regen += lv*5 + lv*max_hp//500 (status.c:2691)
        _sm_rec_lv = mastery.get("SM_RECOVERY", 0)
        if _sm_rec_lv:
            status.hp_regen += _sm_rec_lv * 5 + _sm_rec_lv * status.max_hp // 500

        # MG_SRECOVERY: sp_regen += lv*3 + lv*max_sp//500 (status.c:2694)
        _mg_srec_lv = mastery.get("MG_SRECOVERY", 0)
        if _mg_srec_lv:
            status.sp_regen += _mg_srec_lv * 3 + _mg_srec_lv * status.max_sp // 500

        # NJ_NINPOU: sp_regen += lv*3 + lv*max_sp//500 (status.c:2695)
        _nj_ninpou_lv = mastery.get("NJ_NINPOU", 0)
        if _nj_ninpou_lv:
            status.sp_regen += _nj_ninpou_lv * 3 + _nj_ninpou_lv * status.max_sp // 500

        return status