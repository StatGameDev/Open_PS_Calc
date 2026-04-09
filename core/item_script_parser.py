"""
D5 — Item script parser.
Parses Hercules AtCommands-style scripts: bonus/bonus2/bonus3 calls.

Only bonus types relevant to the damage calculator or tooltips are handled.
Unknown types produce an ItemEffect with description="[{bonus_type} effect]".

Source: Hercules/src/map/script.c (bonus registration table)

Bonus type dispatch is table-driven via BONUS1/BONUS2/BONUS3 from bonus_definitions.py.
Adding a new bonus type requires only one entry there.

parse_sc_start() parses sc_start/sc_start2/sc_start4 calls into SCEffect objects.
Used by GearBonusAggregator (gear_bonus_aggregator.py) for consumable item scripts.

Runtime context evaluation (ItemScriptContext):
  preprocess_script(script, ctx) resolves runtime-dependent values before
  evaluating if/else conditional blocks, so that only the active branches remain.

  Function-call substitutions (regex, before _eval_conditionals):
    getrefine()        → ctx.refine       (script.c; pc.c:8374 SP_STR etc.)
    getskilllv(X)      → ctx.skill_levels.get(X, 0)
    readparam(bStr)    → ctx.str_         (pc.c:8374; sd->status.str = base stat)
    readparam(bAgi)    → ctx.agi
    readparam(bVit)    → ctx.vit
    readparam(bInt)    → ctx.int_
    readparam(bDex)    → ctx.dex
    readparam(bLuk)    → ctx.luk

  Variable substitutions (passed as context to _eval_conditionals):
    BaseLevel          → ctx.base_level   (script.c:2732; SP_BASELEVEL → sd->status.base_level)
    JobLevel           → ctx.job_level    (script.c:2742; SP_JOBLEVEL  → sd->status.job_level)
    Hp                 → ctx.hp           (pc.c; SP_HP    → sd->battle_status.hp)
    MaxHp              → ctx.max_hp       (pc.c; SP_MAXHP → sd->battle_status.max_hp)
    Sp                 → ctx.sp           (pc.c; SP_SP    → sd->battle_status.sp)
    MaxSp              → ctx.max_sp       (pc.c; SP_MAXSP → sd->battle_status.max_sp)
    Class              → ctx.class_       (pc.c; SP_CLASS → sd->status.class)
    BaseJob            → ctx.base_job     (pc.c; SP_BASEJOB)

  Fields set to None are omitted from the context dict; _eval_conditionals
  encounters an unknown variable, returns None from _safe_eval_int, and keeps
  the true branch conservatively — no bonus is silently dropped.

  Arithmetic in bonus parameter positions (e.g. "getrefine()/2" → "8/2") is
  resolved to an integer by _coerce() during the subsequent regex-based bonus
  parsing.

  parse_script() and parse_sc_start() accept ctx=ItemScriptContext(...) and
  preprocess automatically. Passing ctx=None (the default) preserves all prior
  behaviour: refine=0, all unknowns fall through conservatively.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from core.bonus_definitions import BONUS1, BONUS2, BONUS3, BONUS4
from core.models.item_effect import ItemEffect
from core.models.sc_effect import SCEffect


# ---------------------------------------------------------------------------
# Runtime script context
# ---------------------------------------------------------------------------

@dataclass
class ItemScriptContext:
    """All player-side runtime values needed to evaluate item script conditionals.

    Fields map directly to Hercules pc_readparam / script parameter table values.
    Any field left as None causes the corresponding condition to fall through
    conservatively (true branch kept) — no bonus is silently dropped.

    Sources:
      stat fields (str_/agi/vit/int_/dex/luk): pc.c:8374 — sd->status.* (base stat points)
      hp/sp/max_hp/max_sp: pc.c — sd->battle_status.* (computed values)
      base_level/job_level: script.c:2732,2742 — sd->status.base_level/job_level
      class_/base_job: pc.c — sd->status.class / pc_mapid2jobid(sd->job & UPPERMASK)
    """
    refine: int = 0
    skill_levels: dict[str, int] = field(default_factory=dict)

    base_level: int | None = None
    job_level:  int | None = None

    str_: int | None = None
    agi:  int | None = None
    vit:  int | None = None
    int_: int | None = None
    dex:  int | None = None
    luk:  int | None = None

    hp:     int | None = None
    sp:     int | None = None
    max_hp: int | None = None
    max_sp: int | None = None

    class_:   int | None = None
    base_job: int | None = None

    # weapon_level: wlv of the weapon this card is compounded into.
    # Source: script.c:10731 getequipweaponlv — sd->inventory_data[i]->wlv
    # Set only for card slots by GearBonusAggregator.compute() (gear_bonus_aggregator.py).
    weapon_level: int | None = None


# ---------------------------------------------------------------------------
# Safe expression evaluator
# ---------------------------------------------------------------------------

def _eval_node(node: ast.expr, context: dict[str, int]) -> int:
    """Recursively evaluate an AST expression node as an integer.

    Supported constructs:
      - Integer and float literals (floats truncated to int)
      - Named variables resolved via context (unknown names raise ValueError)
      - Unary operators: +, -, not
      - Binary arithmetic: +, -, *, /, //, %
        (both / and // map to C-style integer (floor) division)
      - Comparison chains: ==, !=, <, <=, >, >=  (return 0 or 1)
      - Boolean short-circuit: and, or

    Raises ValueError for unsupported node types or unknown variable names.
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return int(node.value)
        raise ValueError(f"Unsupported constant type: {type(node.value).__name__}")

    if isinstance(node, ast.Name):
        if node.id in context:
            return context[node.id]
        raise ValueError(f"Unknown variable: {node.id!r}")

    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, context)
        if isinstance(node.op, ast.UAdd):   return operand
        if isinstance(node.op, ast.USub):   return -operand
        if isinstance(node.op, ast.Not):    return int(not operand)
        raise ValueError(f"Unsupported unary op: {type(node.op).__name__}")

    if isinstance(node, ast.BinOp):
        left  = _eval_node(node.left,  context)
        right = _eval_node(node.right, context)
        op = node.op
        if isinstance(op, ast.Add):   return left + right
        if isinstance(op, ast.Sub):   return left - right
        if isinstance(op, ast.Mult):  return left * right
        if isinstance(op, (ast.Div, ast.FloorDiv)):
            # Both / and // → integer (floor) division, matching C/Hercules behaviour.
            # Guard against division by zero (returns 0, consistent with C UB convention).
            return left // right if right != 0 else 0
        if isinstance(op, ast.Mod):
            return left % right if right != 0 else 0
        raise ValueError(f"Unsupported binary op: {type(op).__name__}")

    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, context)
        for cmp_op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, context)
            if   isinstance(cmp_op, ast.Eq):    ok = (left == right)
            elif isinstance(cmp_op, ast.NotEq): ok = (left != right)
            elif isinstance(cmp_op, ast.Lt):    ok = (left <  right)
            elif isinstance(cmp_op, ast.LtE):   ok = (left <= right)
            elif isinstance(cmp_op, ast.Gt):    ok = (left >  right)
            elif isinstance(cmp_op, ast.GtE):   ok = (left >= right)
            else: raise ValueError(f"Unsupported comparison op: {type(cmp_op).__name__}")
            if not ok:
                return 0
            left = right
        return 1

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for value in node.values:
                if not _eval_node(value, context):
                    return 0
            return 1
        if isinstance(node.op, ast.Or):
            for value in node.values:
                if _eval_node(value, context):
                    return 1
            return 0
        raise ValueError(f"Unsupported bool op: {type(node.op).__name__}")

    raise ValueError(f"Unsupported AST node type: {type(node).__name__}")


def _safe_eval_int(expr: str, context: dict[str, int]) -> int | None:
    """Safely evaluate a simple integer arithmetic or comparison expression.

    C-style boolean operators (&&, ||) are normalised to Python keywords before
    parsing so the ast module handles them correctly.

    Returns the integer result, or None if:
      - The expression contains unknown variable names not in context.
      - The syntax is unsupported (function calls, subscripts, etc.).
      - A SyntaxError or any other evaluation error occurs.
    """
    # Normalise C-style boolean operators to Python equivalents
    expr = expr.replace('&&', ' and ').replace('||', ' or ')
    try:
        tree = ast.parse(expr.strip(), mode='eval')
    except SyntaxError:
        return None
    try:
        return _eval_node(tree.body, context)
    except (ValueError, ZeroDivisionError, RecursionError):
        return None


# ---------------------------------------------------------------------------
# Conditional block stripper
# ---------------------------------------------------------------------------

def _extract_block(script: str, i: int) -> tuple[str, int]:
    """Extract one block or statement starting at position i.

    Brace form  — script[i] == '{':
        Scans forward counting brace depth, returns the contents between the
        outermost braces (exclusive) and the position after the closing '}'.

    Braceless form — any other character:
        Reads up to and including the next ';', returns that span and the
        position after the semicolon.

    Returns (content: str, new_i: int).
    """
    if i < len(script) and script[i] == '{':
        i += 1          # skip opening '{'
        depth = 1
        start = i
        while i < len(script) and depth > 0:
            c = script[i]
            if   c == '{': depth += 1
            elif c == '}': depth -= 1
            i += 1
        return script[start:i - 1], i   # contents without surrounding braces

    # Braceless single-statement: read to the next semicolon (inclusive)
    start = i
    while i < len(script) and script[i] != ';':
        i += 1
    if i < len(script):
        i += 1  # include the ';'
    return script[start:i], i


def _eval_conditionals(script: str, context: dict[str, int]) -> str:
    """Evaluate all if/else blocks in a pre-substituted script.

    For each if(condition){true}{else false} construct:
      - Evaluates the condition with _safe_eval_int.
      - Keeps the true branch if condition is truthy.
      - Keeps the false branch (if present) if condition is falsy.
      - If the condition references an unknown variable (_safe_eval_int returns
        None), the true branch is kept conservatively so no bonus is silently
        dropped.

    Nested conditionals inside a chosen branch are handled via recursion.
    Non-if characters are passed through unchanged.
    """
    result: list[str] = []
    i = 0
    n = len(script)

    while i < n:
        # Detect the 'if' keyword at a word boundary
        if (script[i:i+2] == 'if'
                and (i == 0 or not (script[i-1].isalnum() or script[i-1] == '_'))
                and (i + 2 >= n  or not (script[i+2].isalnum() or script[i+2] == '_'))):

            # Skip any whitespace between 'if' and the opening '('
            j = i + 2
            while j < n and script[j] in ' \t\n\r':
                j += 1

            if j < n and script[j] == '(':
                # Scan for the matching ')' — handles nested parens inside the condition
                depth = 1
                j += 1
                cond_start = j
                while j < n and depth > 0:
                    if   script[j] == '(': depth += 1
                    elif script[j] == ')': depth -= 1
                    j += 1
                condition = script[cond_start:j - 1]   # text between the outer ( )

                # Skip whitespace before the true branch
                while j < n and script[j] in ' \t\n\r':
                    j += 1

                true_branch, j = _extract_block(script, j)

                # Check for an optional else clause
                k = j
                while k < n and script[k] in ' \t\n\r':
                    k += 1
                false_branch = ""
                if (script[k:k+4] == 'else'
                        and (k + 4 >= n
                             or not (script[k+4].isalnum() or script[k+4] == '_'))):
                    k += 4
                    while k < n and script[k] in ' \t\n\r':
                        k += 1
                    false_branch, k = _extract_block(script, k)
                    j = k

                # Decide which branch to keep
                cond_val = _safe_eval_int(condition.strip(), context)
                if cond_val is None:
                    # Unknown condition → conservative: include true branch
                    chosen = true_branch
                elif cond_val:
                    chosen = true_branch
                else:
                    chosen = false_branch

                # Recurse so nested if/else inside the chosen branch are also evaluated
                result.append(_eval_conditionals(chosen, context))
                i = j
                continue

        result.append(script[i])
        i += 1

    return ''.join(result)


# ---------------------------------------------------------------------------
# Public preprocessor
# ---------------------------------------------------------------------------

_GETREFINE_RE      = re.compile(r'\bgetrefine\s*\(\s*\)')
_GETSKILLLV_RE     = re.compile(r'\bgetskilllv\s*\(\s*(\w+)\s*\)')
# getequipweaponlv(slot_num) → wlv of equipped weapon at that slot.
# Source: script.c:10731 — BUILDIN_DEF(getequipweaponlv,"i")
# Argument is a 1-based index into script->equip[]; we substitute the whole call
# with ctx.weapon_level regardless of the argument (only called from weapon card scripts).
_GETWEAPONLV_RE    = re.compile(r'\bgetequipweaponlv\s*\(\s*\w*\s*\)')

# readparam(bX) → maps the b-prefixed constant to the corresponding context field name.
# Source: pc.c:8374 (SP_STR → sd->status.str = base stat points allocated by player)
_READPARAM_MAP = {
    'bStr': 'str_',
    'bAgi': 'agi',
    'bVit': 'vit',
    'bInt': 'int_',
    'bDex': 'dex',
    'bLuk': 'luk',
}
_READPARAM_RE = re.compile(
    r'\breadparam\s*\(\s*(' + '|'.join(_READPARAM_MAP) + r')\s*\)'
)


def preprocess_script(script: str, ctx: ItemScriptContext | None = None) -> str:
    """Preprocess a Hercules item script for runtime-context-dependent evaluation.

    Steps (applied only when the script contains relevant tokens):

      1. Substitute getrefine() with the literal refine level (ctx.refine).

      1b. Substitute getskilllv(X) with ctx.skill_levels.get(X, 0).
          Skipped if skill_levels is empty.

      1c. Substitute readparam(bX) with the corresponding base stat value
          from ctx (str_, agi, vit, int_, dex, luk).
          Individual stats left as None are not substituted; their conditions
          fall through conservatively in step 2.

      1d. Substitute getequipweaponlv(N) with ctx.weapon_level.
          Raises ValueError if the script contains this call but ctx.weapon_level
          is None — weapon level must always be known for weapon card scripts.
          Source: script.c:10731 BUILDIN(getequipweaponlv)

      2. Evaluate and strip if/else conditional blocks using a context dict
         built from ctx fields that are not None:
           BaseLevel, JobLevel, Hp, MaxHp, Sp, MaxSp, Class, BaseJob.
         Fields set to None are omitted — unknown variables cause _safe_eval_int
         to return None, and _eval_conditionals keeps the true branch
         conservatively so no bonus is silently dropped.

    Passing ctx=None uses refine=0 and omits all variable context, which
    preserves the prior conservative behaviour exactly.

    Scripts containing none of the trigger tokens are returned unchanged.
    """
    if ctx is None:
        ctx = ItemScriptContext()

    has_getrefine    = 'getrefine'        in script
    has_getskilllv   = 'getskilllv'       in script
    has_readparam    = 'readparam'        in script
    has_getweaponlv  = 'getequipweaponlv' in script
    has_if           = 'if(' in script or 'if (' in script

    if not (has_getrefine or has_getskilllv or has_readparam or has_getweaponlv or has_if):
        return script

    # Step 1 — substitute getrefine() with the literal refine level
    if has_getrefine:
        script = _GETREFINE_RE.sub(str(ctx.refine), script)

    # Step 1b — substitute getskilllv(X) with the player's skill level
    if has_getskilllv and ctx.skill_levels:
        script = _GETSKILLLV_RE.sub(
            lambda m: str(ctx.skill_levels.get(m.group(1), 0)), script
        )

    # Step 1c — substitute readparam(bX) with the base stat value
    if has_readparam:
        stat_values: dict[str, int] = {}
        for param_key, field_name in _READPARAM_MAP.items():
            val = getattr(ctx, field_name)
            if val is not None:
                stat_values[param_key] = val
        if stat_values:
            script = _READPARAM_RE.sub(
                lambda m: str(stat_values[m.group(1)])
                          if m.group(1) in stat_values else m.group(0),
                script,
            )

    # Step 1d — substitute getequipweaponlv(N) with the host weapon's wlv.
    # Raises if weapon_level is not set — this call only appears in weapon card scripts
    # and weapon_level must always be injected by GearBonusAggregator (gear_bonus_aggregator.py).
    if has_getweaponlv:
        if ctx.weapon_level is None:
            raise ValueError(
                "getequipweaponlv() in item script but ctx.weapon_level is None — "
                "weapon_level must be set when parsing weapon card scripts"
            )
        script = _GETWEAPONLV_RE.sub(str(ctx.weapon_level), script)

    # Step 2 — evaluate conditional blocks
    # Build var_context from non-None scalar fields (script.c:2732,2742 and pc.c).
    var_context: dict[str, int] = {}
    _VAR_FIELDS = (
        ('BaseLevel', ctx.base_level),
        ('JobLevel',  ctx.job_level),
        ('Hp',        ctx.hp),
        ('MaxHp',     ctx.max_hp),
        ('Sp',        ctx.sp),
        ('MaxSp',     ctx.max_sp),
        ('Class',     ctx.class_),
        ('BaseJob',   ctx.base_job),
    )
    for name, val in _VAR_FIELDS:
        if val is not None:
            var_context[name] = val

    script = _eval_conditionals(script, var_context)

    return script


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# Matches: bonus bXxx,val | bonus2 bXxx,a,b | bonus3 bXxx,a,b,c | bonus4 bXxx,a,b,c,d
# Also handles: bonus bXxx val  (space-separated)
_BONUS_RE = re.compile(
    r'\bbonus(2|3|4)?\s+'      # "bonus", "bonus2", "bonus3", or "bonus4"
    r'(b\w+)'                  # bonus type e.g. bStr
    r'(?:[,\s](.+?))?'         # optional params (lazy, to next semicolon or end)
    r'(?=;|$)',                # lookahead: ends at semicolon or EOL
    re.MULTILINE,
)

# Matches: skill SKILL_CONSTANT,level  (grants the player the skill temporarily).
# Source: Hercules script.c — skill command calls pc_skill(sd, id, lv, ADDSKILL_TEMP).
_SKILL_RE = re.compile(
    r'\bskill\s+(\w+)\s*,\s*(\d+)',
    re.MULTILINE,
)


def _coerce(s: str) -> int | str:
    """Convert a bonus parameter string to int.

    Tries in order:
      1. Direct int() conversion — handles plain integer literals.
      2. Safe arithmetic evaluation via _safe_eval_int — handles expressions
         such as "8/2" that arise after getrefine() substitution.
      3. Return the original string — for named constants (RC_Fish, SC_POISON…).
    """
    s = s.strip()
    try:
        return int(s)
    except ValueError:
        pass
    val = _safe_eval_int(s, {})
    if val is not None:
        return val
    return s


def parse_script(script: str, ctx: ItemScriptContext | None = None) -> list[ItemEffect]:
    """Parse a Hercules item script string into a list of ItemEffect objects.

    ctx: runtime context used to evaluate getrefine(), getskilllv(), readparam(),
         and conditional blocks. Pass None (default) for the prior conservative
         behaviour (refine=0, unknown conditions keep true branch).
    """
    if not script:
        return []

    script = preprocess_script(script, ctx)
    effects: list[ItemEffect] = []

    for m in _BONUS_RE.finditer(script):
        arity_suffix = m.group(1)  # None, "2", "3", or "4"
        arity = int(arity_suffix) if arity_suffix else 1
        bonus_type = m.group(2)
        raw_params = m.group(3) or ""

        # Split params on comma; first param for arity-1 may be the only token
        parts = [p.strip() for p in raw_params.split(",") if p.strip()]
        params = [_coerce(p) for p in parts]

        description = _make_description(bonus_type, arity, params)

        effects.append(ItemEffect(
            bonus_type=bonus_type,
            arity=arity,
            params=params,
            description=description,
        ))

    for m in _SKILL_RE.finditer(script):
        skill_name = m.group(1)
        level = int(m.group(2))
        effects.append(ItemEffect(
            bonus_type="skill",
            arity=2,
            params=[skill_name, level],
            description=f"Grants {skill_name} level {level}",
        ))

    return effects


def _make_description(bonus_type: str, arity: int, params: list) -> str:
    defn = {1: BONUS1, 2: BONUS2, 3: BONUS3, 4: BONUS4}.get(arity, {}).get(bonus_type)
    if defn is None or len(params) < arity:
        return f"[{bonus_type} effect]"
    try:
        return defn.description(*params[:arity])
    except Exception:
        return f"[{bonus_type} effect]"


# ---------------------------------------------------------------------------
# sc_start parser
# ---------------------------------------------------------------------------

# Matches sc_start / sc_start2 / sc_start4 in both forms:
#   sc_start  SC_NAME, dur, v1, ...;
#   sc_start4(SC_NAME, dur, v1, ...);
# Captures the variant suffix and the SC_NAME; remaining tokens parsed below.
_SC_START_RE = re.compile(
    r'\bsc_start(2|4)?\s*\(?\s*'   # sc_start, sc_start2, sc_start4; optional '('
    r'(SC_\w+)'                      # SC_NAME constant
    r'((?:\s*,\s*-?[\w.]+)*)',       # zero or more comma-separated tokens
    re.MULTILINE,
)


def parse_sc_start(script: str, ctx: ItemScriptContext | None = None) -> list[SCEffect]:
    """
    Parse all sc_start / sc_start2 / sc_start4 calls in a Hercules item script.

    ctx: runtime context passed to preprocess_script() so context-conditional
         sc_start calls are correctly included or excluded.

    Returns a list of SCEffect objects.  Non-numeric tokens (e.g. SCFLAG_NONE,
    Ele_Neutral) are silently skipped when collecting val1–val4.

    Duration of -1 means permanent (OnEquip).  For val ordering:
    - sc_start  args: sc_name, duration, val1[, val2][, val3]
    - sc_start2 args: sc_name, duration, val1, val2  (same storage, different internal route)
    - sc_start4 args: sc_name, duration, val1, val2, val3, val4
    """
    if not script:
        return []

    script = preprocess_script(script, ctx)
    effects: list[SCEffect] = []

    for m in _SC_START_RE.finditer(script):
        sc_name = m.group(2)
        raw_tokens = m.group(3) or ""

        # Split on commas; convert numeric tokens; skip non-numeric (flags, ele names)
        numeric: list[int] = []
        for tok in raw_tokens.split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                numeric.append(int(tok))
            except ValueError:
                pass  # SCFLAG_NONE, Ele_Neutral, etc.

        if not numeric:
            # No duration found — malformed; skip
            continue

        duration_ms = numeric[0]
        vals = numeric[1:]  # val1..val4
        effects.append(SCEffect(
            sc_name=sc_name,
            duration_ms=duration_ms,
            val1=vals[0] if len(vals) > 0 else 0,
            val2=vals[1] if len(vals) > 1 else 0,
            val3=vals[2] if len(vals) > 2 else 0,
            val4=vals[3] if len(vals) > 3 else 0,
        ))

    return effects
