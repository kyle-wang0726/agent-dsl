# src/agent_dsl/runtime.py
from typing import Iterable, Dict, Any, List, Optional, Callable, Tuple
import ast
import json
import re
from pathlib import Path
from .parser import Program, Flow, Action

# 可选导入 LLM
try:
    from .llm_agent import DeepSeekClient
except Exception:
    DeepSeekClient = None  # 允许没有 llm_agent.py 时正常运行（不启用 LLM）

# =========================
# 字符串插值（支持过滤器管道）
# =========================

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
    return s

def _parse_pipeline(inner: str) -> tuple[str, list[tuple[str, Optional[str]]]]:
    parts: list[str] = []
    buf: list[str] = []
    in_quotes = False
    escape = False
    for ch in inner:
        if escape:
            buf.append(ch); escape = False; continue
        if ch == '\\':
            buf.append(ch); escape = True; continue
        if ch == '"':
            buf.append(ch); in_quotes = not in_quotes; continue
        if ch == '|' and not in_quotes:
            parts.append(''.join(buf).strip()); buf = []; continue
        buf.append(ch)
    if buf: parts.append(''.join(buf).strip())
    if not parts: return "", []
    var = parts[0].strip()
    filters: list[tuple[str, Optional[str]]] = []
    for seg in parts[1:]:
        m = re.match(r'^([a-zA-Z_]\w*)(?:\s*:\s*"((?:\\.|[^"])*)")?\s*$', seg)
        if not m: continue
        fname = m.group(1)
        farg  = _unescape_filter_arg(m.group(2)) if m.group(2) is not None else None
        filters.append((fname, farg))
    return var, filters

def _interpolate(s: str, ctx: Dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        inner = m.group(1)
        var, filters = _parse_pipeline(inner)
        val: Any = ctx.get(var, "")
        for fname, farg in filters:
            val = _apply_filter(val, fname, farg)
        return "" if val is None else str(val)
    return _VAR_TAG_RE.sub(repl, s)

# =========================
# 表达式求值（严格白名单）
# =========================

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)
_ALLOWED_UNARY  = (ast.UAdd, ast.USub)

def _fn_len(x):    return len(str(x))
def _fn_abs(x):    return abs(float(x))
def _fn_int(x):    return int(float(x))
def _fn_float(x):  return float(x)
def _fn_str(x):    return str(x)
def _fn_upper(x):  return str(x).upper()
def _fn_lower(x):  return str(x).lower()
def _fn_title(x):  return str(x).title()
def _fn_trim(x):   return str(x).strip()
def _fn_min(a, b): return min(float(a), float(b))
def _fn_max(a, b): return max(float(a), float(b))
# ⭐ 新增：子串包含
def _fn_contains(h, n): return str(n) in str(h)

_FUNC_WHITELIST = {
    "len": _fn_len, "abs": _fn_abs,
    "int": _fn_int, "float": _fn_float, "str": _fn_str,
    "upper": _fn_upper, "lower": _fn_lower, "title": _fn_title, "trim": _fn_trim,
    "min": _fn_min, "max": _fn_max,
    "contains": _fn_contains,
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
    if isinstance(node, ast.Expression):
        return _eval_value_node(node.body, ctx)

    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
        l = _eval_value_node(node.left, ctx)
        r = _eval_value_node(node.right, ctx)
        ln, rn = _coerce_number(l), _coerce_number(r)
        if isinstance(ln, (int, float)) and isinstance(rn, (int, float)):
            if   isinstance(node.op, ast.Add):      return ln + rn
            elif isinstance(node.op, ast.Sub):      return ln - rn
            elif isinstance(node.op, ast.Mult):     return ln * rn
            elif isinstance(node.op, ast.Div):      return ln / rn
            elif isinstance(node.op, ast.FloorDiv): return ln // rn
            elif isinstance(node.op, ast.Mod):      return ln % rn
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
        low = name.lower()
        if low == "true":  return True
        if low == "false": return False
        if low == "null":  return None
        return ctx.get(name, "")

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Call):
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

# =========================
# 比较与布尔表达式
# =========================

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

# 旧式 if_goto 兼容
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

def _eval_bool(expr: str, ctx: Dict[str, str]) -> bool:
    tree = ast.parse(expr, mode="eval")

    def ev(node: ast.AST) -> bool:
        if isinstance(node, ast.Expression):
            return ev(node.body)

        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                for v in node.values:
                    if not ev(v): return False
                return True
            if isinstance(node.op, ast.Or):
                for v in node.values:
                    if ev(v): return True
                return False
            raise ValueError("仅支持 and / or")

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not ev(node.operand)

        if isinstance(node, ast.Compare):
            left_val = _eval_value_node(node.left, ctx)
            cur = left_val
            for op, comp in zip(node.ops, node.comparators):
                right_val = _eval_value_node(comp, ctx)
                if   isinstance(op, ast.Eq):    ok = _do_compare(cur, "==", right_val)
                elif isinstance(op, ast.NotEq): ok = _do_compare(cur, "!=", right_val)
                elif isinstance(op, ast.Gt):    ok = _do_compare(cur, ">",  right_val)
                elif isinstance(op, ast.Lt):    ok = _do_compare(cur, "<",  right_val)
                elif isinstance(op, ast.GtE):   ok = _do_compare(cur, ">=", right_val)
                elif isinstance(op, ast.LtE):   ok = _do_compare(cur, "<=", right_val)
                else:
                    raise ValueError("比较运算仅支持 == != > < >= <=")
                if not ok: return False
                cur = right_val
            return True

        if isinstance(node, (ast.Constant, ast.Name, ast.BinOp, ast.UnaryOp, ast.Call)):
            v = _eval_value_node(node, ctx)
            if isinstance(v, (int, float)): return v != 0
            return bool(v)

        raise ValueError(f"不允许的布尔表达式：{ast.dump(node, include_attributes=False)}")

    return ev(tree)

# =========================
# 引擎
# =========================

class Engine:
    def __init__(self, program: Program, flow_name: str = "main",
                 context: Optional[Dict[str, str]] = None,
                 ask_fn=None, debug: bool = False, use_llm: bool = False,
                 printer: Optional[Callable[[str], None]] = None):
        if flow_name not in program.flows:
            raise KeyError(f"找不到 flow: {flow_name}")
        self.flow: Flow = program.flows[flow_name]
        if not self.flow.states:
            raise ValueError("该 flow 下没有任何 state")
        self.state_name = next(iter(self.flow.states.keys()))
        self.ctx: Dict[str, str] = dict(context or {})
        self.ask_fn = ask_fn
        self.debug = debug
        self.use_llm = use_llm
        self.printer = printer or print  # ← 用于 ask 前立即输出

        self.llm_client = DeepSeekClient() if (use_llm and DeepSeekClient is not None) else None
        self._last_asked_var: Optional[str] = None
        self._visits: Dict[str, int] = {}
        self.fallback_state: Optional[str] = None
        for name in ("fallback", "unknown", "end"):
            if name in self.flow.states:
                self.fallback_state = name
                break

    def _exec_actions(self, actions: List[Action], buffer: List[str]) -> Optional[str]:
        """
        actions：当前状态内的动作
        buffer：reply 输出缓冲；遇到 ask 时立刻 flush 到终端
        """
        for act in actions:
            k = act.kind
            a = act.args

            if k == "reply":
                buffer.append(_interpolate(a["text"], self.ctx))

            elif k == "set":
                self.ctx[a["var"]] = a["value"]

            elif k == "set_expr":
                val = _eval_expr(a["expr"], self.ctx)
                self.ctx[a["var"]] = "" if val is None else str(val)

            elif k == "ask":
                # 在提示之前，把已有回复立即输出，保证顺序正确
                if buffer:
                    for line in buffer:
                        self.printer(line)
                    buffer.clear()

                var, prompt = a["var"], a["prompt"]
                if var not in self.ctx:
                    self.ctx[var] = self.ask_fn(var, prompt) if self.ask_fn else input(prompt)
                self._last_asked_var = var  # 记录最后一次问到哪个变量

            elif k == "if_goto":
                left = self.ctx.get(a["left"], "")
                if _compare(str(left), "==", str(a["right"])):
                    return a["target"]

            elif k == "if_chain":
                fired = False
                for br in a["branches"]:
                    if _eval_bool(br["cond"], self.ctx):
                        ret = self._exec_actions(br["actions"], buffer)
                        if ret is not None:
                            return ret
                        fired = True
                        break
                if not fired and a.get("else"):
                    ret = self._exec_actions(a["else"], buffer)
                    if ret is not None:
                        return ret

            elif k == "if_block":  # 兼容旧版
                left_val  = _eval_expr(a["left"],  self.ctx)
                right_val = _eval_expr(a["right"], self.ctx)
                branch: List[Action] = a["then"] if _do_compare(left_val, a["op"], right_val) else (a.get("else") or [])
                ret = self._exec_actions(branch, buffer)
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
        """
        流式执行当前 flow：
        - reply 先写入缓冲，遇到 ask 会先 flush 再弹出提示
        - 状态末尾若没有跳转：如果有最近问到的变量，才用 LLM 进行兜底路由
        """
        guard = 0
        while True:
            guard += 1
            if guard > 2000:
                raise RuntimeError("可能出现死循环")

            self._visits[self.state_name] = self._visits.get(self.state_name, 0) + 1
            self._last_asked_var = None  # 进入新状态，重置

            state = self.flow.states[self.state_name]
            buffer: List[str] = []
            target = self._exec_actions(state.actions, buffer)

            # 把状态内剩余的输出统一吐出（若中间没有 ask，这里会一次性输出）
            for line in buffer:
                yield line

            # 若还没有跳转 → 尝试 LLM 兜底（仅当本状态确实问过一次）
            if target is None and self.use_llm and self.llm_client and self._last_asked_var:
                user_text = self.ctx.get(self._last_asked_var, "")
                suggestion = self.llm_client.classify_intent(
                    user_text,
                    list(self.flow.states.keys()),
                    exclude=[self.state_name],
                )
                if suggestion and suggestion in self.flow.states and suggestion != self.state_name:
                    yield f"(LLM判定意图：{suggestion})"
                    target = suggestion

            # 仍未跳转：同一状态停留>=2 次 → 兜底到 fallback（若存在）
            if target is None and self.fallback_state and self._visits.get(self.state_name, 0) >= 2:
                target = self.fallback_state

            if target is not None:
                if target not in self.flow.states:
                    raise KeyError(f"goto 的目标状态不存在：{target}")
                self.state_name = target
                continue

            break
