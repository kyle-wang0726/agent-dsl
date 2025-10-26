from typing import Iterable, Dict, Any, List, Optional, Callable, Tuple
import ast
import json
import re
from pathlib import Path
from .parser import Program, Flow, Action

# ====== 插值：支持过滤器 {{ name | upper }} / {{ name | default:"游客" }} / {{ name | trim }} ======
# 变量名 + 可选单个过滤器
_VAR_TAG_RE = re.compile(r"\{\{\s*(.*?)\s*\}\}")

def _unescape_filter_arg(text: str) -> str:
    return text.replace(r'\"', '"').replace(r'\\', '\\')

def _apply_filter(value: Any, filt: str, arg: Optional[str]) -> Any:
    s = "" if value is None else str(value)
    f = filt.lower()
    if f == "upper":   return s.upper()
    if f == "lower":   return s.lower()
    if f == "title":   return s.title()
    if f == "trim":    return s.strip()
    if f == "default": return s if s != "" else (arg or "")
    # 未知过滤器：原样返回字符串
    return s

def _parse_pipeline(inner: str) -> tuple[str, list[tuple[str, Optional[str]]]]:
    # 手动分段：按 '|' 切分，但跳过引号内部
    parts: list[str] = []
    buf: list[str] = []
    in_quotes = False
    escape = False
    for ch in inner:
        if escape:
            buf.append(ch)
            escape = False
            continue
        if ch == '\\':
            buf.append(ch)
            escape = True
            continue
        if ch == '"':
            buf.append(ch)
            in_quotes = not in_quotes
            continue
        if ch == '|' and not in_quotes:
            parts.append(''.join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if buf:
        parts.append(''.join(buf).strip())

    if not parts:
        return "", []

    var = parts[0].strip()
    filters: list[tuple[str, Optional[str]]] = []
    for seg in parts[1:]:
        # 允许：filt    或    filt : "arg"
        m = re.match(r'^([a-zA-Z_]\w*)(?:\s*:\s*"((?:\\.|[^"])*)")?\s*$', seg)
        if not m:
            # 非法段落，忽略该过滤器
            continue
        fname = m.group(1)
        farg  = _unescape_filter_arg(m.group(2)) if m.group(2) is not None else None
        filters.append((fname, farg))
    return var, filters

def _interpolate(s: str, ctx: Dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        inner = m.group(1)
        var, filters = _parse_pipeline(inner)
        # 变量取值
        val: Any = ctx.get(var, "")
        # 依次应用过滤器
        for fname, farg in filters:
            val = _apply_filter(val, fname, farg)
        return "" if val is None else str(val)
    return _VAR_TAG_RE.sub(repl, s)

# ====== 表达式求值（安全白名单） ======
_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)
_ALLOWED_UNARY  = (ast.UAdd, ast.USub)

# 白名单函数
def _fn_len(x):   return len(str(x))
def _fn_abs(x):   return abs(float(x))
def _fn_int(x):   return int(float(x))
def _fn_float(x): return float(x)
def _fn_str(x):   return str(x)
def _fn_upper(x): return str(x).upper()
def _fn_lower(x): return str(x).lower()
def _fn_title(x): return str(x).title()
def _fn_trim(x):  return str(x).strip()
def _fn_min(a, b): return min(float(a), float(b))
def _fn_max(a, b): return max(float(a), float(b))

_FUNC_WHITELIST = {
    "len": _fn_len, "abs": _fn_abs,
    "int": _fn_int, "float": _fn_float, "str": _fn_str,
    "upper": _fn_upper, "lower": _fn_lower, "title": _fn_title, "trim": _fn_trim,
    "min": _fn_min, "max": _fn_max,
}

def _coerce_number(v: Any) -> Any:
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v)
    try:
        return float(s)
    except Exception:
        return v

def _eval_value_node(node: ast.AST, ctx: Dict[str, str]) -> Any:
    """数值/字符串表达式求值：常量、变量、()、+ - * / // %、一元±、白名单函数调用。"""
    if isinstance(node, ast.Expression):
        return _eval_value_node(node.body, ctx)

    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
        l = _eval_value_node(node.left, ctx)
        r = _eval_value_node(node.right, ctx)
        ln, rn = _coerce_number(l), _coerce_number(r)
        if isinstance(ln, (int, float)) and isinstance(rn, (int, float)):
            if isinstance(node.op, ast.Add): return ln + rn
            if isinstance(node.op, ast.Sub): return ln - rn
            if isinstance(node.op, ast.Mult): return ln * rn
            if isinstance(node.op, ast.Div): return ln / rn
            if isinstance(node.op, ast.FloorDiv): return ln // rn
            if isinstance(node.op, ast.Mod): return ln % rn
        if isinstance(node.op, ast.Add) and isinstance(l, str) and isinstance(r, str):
            return l + r
        raise ValueError("仅支持数字算术或字符串相加")

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARY):
        v = _eval_value_node(node.operand, ctx)
        vn = _coerce_number(v)
        if isinstance(vn, (int, float)):
            return +vn if isinstance(node.op, ast.UAdd) else -vn
        raise ValueError("一元正负仅支持数字")

    if isinstance(node, ast.Name):
        name = node.id
        # true/false/null（大小写不敏感）
        low = name.lower()
        if low == "true":  return True
        if low == "false": return False
        if low == "null":  return None
        return ctx.get(name, "")

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Call):
        # 仅允许调用白名单内的简单函数
        if isinstance(node.func, ast.Name) and node.func.id in _FUNC_WHITELIST:
            fn = _FUNC_WHITELIST[node.func.id]
            args = [_eval_value_node(a, ctx) for a in node.args]
            return fn(*args)
        raise ValueError("仅允许白名单函数调用")

    if isinstance(node, ast.Subscript) or isinstance(node, ast.Attribute):
        raise ValueError("不允许下标/属性访问")

    raise ValueError(f"表达式不被允许：{ast.dump(node, include_attributes=False)}")

def _eval_expr(expr: str, ctx: Dict[str, str]) -> Any:
    return _eval_value_node(ast.parse(expr, mode="eval"), ctx)

# ====== 比较：两个都能转数字 → 数值比较；否则字符串比较 ======
def _to_number_maybe(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v))
    except Exception:
        return None

def _as_numbers(a: Any, b: Any) -> Optional[Tuple[float, float]]:
    fa = _to_number_maybe(a)
    fb = _to_number_maybe(b)
    if fa is not None and fb is not None:
        return (fa, fb)
    return None

def _do_compare(a: Any, op: str, b: Any) -> bool:
    nums = _as_numbers(a, b)
    if nums is not None:
        a_num, b_num = nums
        if     op == "==": return a_num == b_num
        elif   op == "!=": return a_num != b_num
        elif   op ==  ">": return a_num >  b_num
        elif   op ==  "<": return a_num <  b_num
        elif   op == ">=": return a_num >= b_num
        elif   op == "<=": return a_num <= b_num
    else:
        a_str, b_str = str(a), str(b)
        if     op == "==": return a_str == b_str
        elif   op == "!=": return a_str != b_str
        elif   op ==  ">": return a_str >  b_str
        elif   op ==  "<": return a_str <  b_str
        elif   op == ">=": return a_str >= b_str
        elif   op == "<=": return a_str <= b_str
    raise ValueError(f"不支持的操作符：{op}")

# ====== 旧式 if_goto 兼容 ======
def _to_number(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None

def _compare(a: str, op: str, b: str) -> bool:
    na, nb = _to_number(a), _to_number(b)
    if na is not None and nb is not None:
        if   op == "==": return na == nb
        elif op == "!=": return na != nb
        elif op ==  ">": return na >  nb
        elif op ==  "<": return na <  nb
        elif op == ">=": return na >= nb
        elif op == "<=": return na <= nb
    else:
        if   op == "==": return a == b
        elif op == "!=": return a != b
        elif op ==  ">": return a >  b
        elif op ==  "<": return a <  b
        elif op == ">=": return a >= b
        elif op == "<=": return a <= b
    raise ValueError(f"不支持的操作符：{op}")

# ====== 新：布尔表达式（and/or/not、比较链） ======
def _eval_bool(expr: str, ctx: Dict[str, str]) -> bool:
    tree = ast.parse(expr, mode="eval")

    def ev(node: ast.AST) -> bool:
        if isinstance(node, ast.Expression):
            return ev(node.body)

        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                for v in node.values:
                    if not ev(v):
                        return False
                return True
            if isinstance(node.op, ast.Or):
                for v in node.values:
                    if ev(v):
                        return True
                return False
            raise ValueError("仅支持 and / or")

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not ev(node.operand)

        if isinstance(node, ast.Compare):
            left_val = _eval_value_node(node.left, ctx)
            cur = left_val
            for op, comp in zip(node.ops, node.comparators):
                right_val = _eval_value_node(comp, ctx)
                if   isinstance(op, ast.Eq):  ok = _do_compare(cur, "==", right_val)
                elif isinstance(op, ast.NotEq): ok = _do_compare(cur, "!=", right_val)
                elif isinstance(op, ast.Gt):   ok = _do_compare(cur, ">",  right_val)
                elif isinstance(op, ast.Lt):   ok = _do_compare(cur, "<",  right_val)
                elif isinstance(op, ast.GtE):  ok = _do_compare(cur, ">=", right_val)
                elif isinstance(op, ast.LtE):  ok = _do_compare(cur, "<=", right_val)
                else:
                    raise ValueError("比较运算仅支持 == != > < >= <=")
                if not ok:
                    return False
                cur = right_val
            return True

        if isinstance(node, (ast.Constant, ast.Name, ast.BinOp, ast.UnaryOp, ast.Call)):
            v = _eval_value_node(node, ctx)
            if isinstance(v, (int, float)):
                return v != 0
            return bool(v)

        raise ValueError(f"不允许的布尔表达式：{ast.dump(node, include_attributes=False)}")

    return ev(tree)

class Engine:
    def __init__(self, program: Program, flow_name: str = "main",
                 context: Optional[Dict[str, str]] = None, ask_fn=None, debug: bool = False):
        if flow_name not in program.flows:
            raise KeyError(f"找不到 flow: {flow_name}")
        self.flow: Flow = program.flows[flow_name]
        if not self.flow.states:
            raise ValueError("该 flow 下没有任何 state")
        self.state_name = next(iter(self.flow.states.keys()))
        self.ctx: Dict[str, str] = dict(context or {})
        self.ask_fn = ask_fn
        self.debug = debug

    def _exec_actions(self, actions: List[Action], emit: Callable[[str], None]) -> Optional[str]:
        for act in actions:
            k = act.kind
            a = act.args

            if k == "reply":
                emit(_interpolate(a["text"], self.ctx))

            elif k == "set":
                self.ctx[a["var"]] = a["value"]

            elif k == "set_expr":
                val = _eval_expr(a["expr"], self.ctx)
                # 统一存为字符串，便于插值；算术时可再次被 _coerce_number 转成数字
                self.ctx[a["var"]] = "" if val is None else str(val)

            elif k == "ask":
                var, prompt = a["var"], a["prompt"]
                if var not in self.ctx:
                    self.ctx[var] = self.ask_fn(var, prompt) if self.ask_fn else input(prompt)

            elif k == "if_goto":
                left = self.ctx.get(a["left"], "")
                if _compare(str(left), "==", str(a["right"])):
                    return a["target"]

            elif k == "if_chain":
                fired = False
                for br in a["branches"]:
                    cond = br["cond"]
                    if _eval_bool(cond, self.ctx):
                        ret = self._exec_actions(br["actions"], emit)
                        if ret is not None:
                            return ret
                        fired = True
                        break
                if not fired and a.get("else"):
                    ret = self._exec_actions(a["else"], emit)
                    if ret is not None:
                        return ret

            elif k == "if_block":  # 兼容旧版（左右为表达式的比较）
                left_val  = _eval_expr(a["left"],  self.ctx)
                right_val = _eval_expr(a["right"], self.ctx)
                branch: List[Action] = br["actions"] if False else []  # 占位避免编辑器误判

                branch = a["then"] if _do_compare(left_val, a["op"], right_val) else (a.get("else") or [])
                ret = self._exec_actions(branch, emit)
                if ret is not None:
                    return ret

            elif k == "goto":
                return a["target"]

            elif k == "save":
                p = Path(a["path"])
                p.parent.mkdir(parents=True, exist_ok=True)
                data: Dict[str, Any] = {}
                if p.exists():
                    try:
                        data = json.loads(p.read_text(encoding="utf-8") or "{}")
                    except Exception:
                        data = {}
                data[a["var"]] = str(self.ctx.get(a["var"], ""))
                p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

            elif k == "load":
                p = Path(a["path"])
                if p.exists():
                    try:
                        data = json.loads(p.read_text(encoding="utf-8"))
                        if isinstance(data, dict) and a["var"] in data:
                            self.ctx[a["var"]] = str(data[a["var"]])
                    except Exception:
                        pass

            else:
                raise ValueError(f"未知动作：{k}")
        return None

    def run_iter(self) -> Iterable[str]:
        guard = 0
        while True:
            guard += 1
            if guard > 2000:
                raise RuntimeError("可能出现死循环")
            state = self.flow.states[self.state_name]

            buffer: List[str] = []
            target = self._exec_actions(state.actions, buffer.append)

            for line in buffer:
                yield line

            if target is not None:
                if target not in self.flow.states:
                    raise KeyError(f"goto 的目标状态不存在：{target}")
                self.state_name = target
                continue
            break
