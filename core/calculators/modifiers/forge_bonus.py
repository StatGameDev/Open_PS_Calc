"""ForgeBonus — G17 forged weapon star crumb ATK bonus.

Applied after AttrFix and before CardFix, per hit count (div).
Source: status.c:1634-1643 (CARD0_FORGE decoding, no RENEWAL guard)
        battle.c:5864 (#ifndef RENEWAL):
            ATK_ADD2(wd.div_*sd->right_weapon.star, wd.div_*sd->left_weapon.star)

Star computation (status.c:1634-1643):
    star += (card[1] >> 8)          # card[1] encoded as (sc_count * 5) << 8
    if star >= 15: star = 40        # 3 crumbs → clamped to 40
    if ranked_blacksmith: star += 10

star × div is added flat after AttrFix; CardFix (% bonuses) then applies on top.
"""

from core.models.weapon import Weapon
from core.models.damage import DamageResult
from pmf.operations import pmf_stats


class ForgeBonus:
    @staticmethod
    def calculate(weapon: Weapon, div: int, pmf: dict, result: DamageResult) -> dict:
        """Add forge star ATK bonus flat per hit (star × div) after AttrFix.

        div: hit count for the current skill (1 for normal attacks).
        Returns updated pmf.
        """
        sc = weapon.forge_sc_count
        if sc == 0 and not weapon.forge_ranked:
            return pmf

        # status.c:1636-1641
        star = sc * 5                   # card[1]>>8 = sc*5 (encoding: sc*5 << 8)
        if star >= 15:
            star = 40                   # 3 crumbs clamped to 40 (not 45)
        if weapon.forge_ranked:
            star += 10                  # ranked blacksmith bonus

        if star == 0:
            return pmf

        flat = star * div               # battle.c:5864: ATK_ADD2(wd.div_ * star, ...)
        out_pmf = {k + flat: v for k, v in pmf.items()}

        mn, mx, av = pmf_stats(out_pmf)
        result.add_step(
            "Forge Bonus",
            value=av, min_value=mn, max_value=mx,
            note=(
                f"{sc} crumb(s){'+ Ranked' if weapon.forge_ranked else ''} "
                f"→ star={star}, ×div{div} = +{flat} flat"
            ),
            formula=f"star({star}) × div({div}) = +{flat}",
            hercules_ref=(
                "status.c:1634-1643 (CARD0_FORGE decode); "
                "battle.c:5864 (#ifndef RENEWAL): ATK_ADD2(wd.div_*right_weapon.star, ...)"
            ),
        )
        return out_pmf
