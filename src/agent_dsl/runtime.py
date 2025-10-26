# src/agent_dsl/runtime.py
from typing import Iterable, Dict, Any, List, Optional, Callable, Tuple
import ast
import json
import re
from pathlib import Path
from .parser import Program, Flow, Action

_VAR_PATTERN = re.compile(r"\{\{(\w+)\}\}")

def _interpolate(s: str, ctx: Dict[str, str]) -> str:
    def repl(m):
        key = m.group(1)
        return str(ctx.get(key, f"{{{{{key}}}}}"))
    return _VAR_PATTERN.sub(repl, s)

# ===== 安全表达式求值（仅支持数值/字符串运算） =====
_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)
_ALLOWED_UNARY  = (ast.UAdd, ast.USub)

def _coerce_number(v: Any) -> Any:
    """尽量把字符串转成 float；转不动就原样返回（用于字符串比较/插值）。"""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v)
    try:
        return float(s)
    except Exception:
        return v  # 保持原样（字符串）

def _eval_expr(expr: str, ctx: Dict[str, str]) -> Any:
    """
    只允许：常量(数字/字符串)、变量、括号、
           一元 +/−、二元 + − * / // % 。
    不允许函数调用/属性/下标等。
    """
    tree = ast.parse(expr, mode="eval")

    def ev(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
            l, r = ev(node.left), ev(node.right)
            l_num, r_num = _coerce_number(l), _coerce_number(r)
            # 两侧都是数字 → 算术
            if isinstance(l_num, (int, float)) and isinstance(r_num, (int, float)):
                if isinstance(node.op, ast.Add): return l_num + r_num
                if isinstance(node.op, ast.Sub): return l_num - r_num
                if isinstance(node.op, ast.Mult): return l_num * r_num
                if isinstance(node.op, ast.Div): return l_num / r_num
                if isinstance(node.op, ast.FloorDiv): return l_num // r_num
                if isinstance(node.op, ast.Mod): return l_num % r_num
            # 字符串拼接（只允许 +）
            if isinstance(node.op, ast.Add) and isinstance(l, str) and isinstance(r, str):
                return l + r
            raise ValueError("仅支持数字算术或字符串相加")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARY):
            v = ev(node.operand)
            v_num = _coerce_number(v)
            if isinstance(v_num, (int, float)):
                return +v_num if isinstance(node.op, ast.UAdd) else -v_num
            raise ValueError("一元正负仅支持数字")
        if isinstance(node, ast.Name):
            # 变量可能被用于数字或字符串，原样返回
            return ctx.get(node.id, "")
        if isinstance(node, ast.Constant):
            return node.value
        raise ValueError(f"表达式不被允许：{ast.dump(node, include_attributes=False)}")

    return ev(tree)

# ===== 比较：两个都能转成数字 → 数值比较；否则字符串比较（解决类型告警） =====
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
    """
    显式缩窄类型：
    - 如果能拿到 (float, float)，在该分支做 > < >= <= 等比较（Pylance 不会报错）
    - 否则回退到 (str, str) 比较
    """
    nums = _as_numbers(a, b)
    if nums is not None:
        a_num, b_num = nums  # (float, float)
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

# ===== 旧式等值判断（行内 if_goto 仍保留兼容） =====
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

class Engine:
    def __init__(self, program: Program, flow_name: str = "main",
                 context: Optional[Dict[str, str]] = None, ask_fn=None):
        if flow_name not in program.flows:
            raise KeyError(f"找不到 flow: {flow_name}")
        self.flow: Flow = program.flows[flow_name]
        if not self.flow.states:
            raise ValueError("该 flow 下没有任何 state")
        self.state_name = next(iter(self.flow.states.keys()))
        self.ctx: Dict[str, str] = dict(context or {})
        self.ask_fn = ask_fn

    def _exec_actions(self, actions: List[Action], emit: Callable[[str], None]) -> Optional[str]:
        """执行动作列表。遇到 goto 返回目标状态名；否则返回 None。通过 emit 输出 reply 文本。"""
        for act in actions:
            k = act.kind
            a = act.args
            if k == "reply":
                emit(_interpolate(a["text"], self.ctx))

            elif k == "set":
                self.ctx[a["var"]] = a["value"]

            elif k == "ask":
                var, prompt = a["var"], a["prompt"]
                if var not in self.ctx:
                    self.ctx[var] = self.ask_fn(var, prompt) if self.ask_fn else input(prompt)

            elif k == "if_goto":
                left = self.ctx.get(a["left"], "")
                if _compare(str(left), "==", str(a["right"])):
                    return a["target"]

            elif k == "if_block":
                # 左右两边是【表达式字符串】→ 先求值，再比较
                left_val  = _eval_expr(a["left"],  self.ctx)
                right_val = _eval_expr(a["right"], self.ctx)
                branch: List[Action] = a["then"] if _do_compare(left_val, a["op"], right_val) else (a.get("else") or [])
                ret = self._exec_actions(branch, emit)
                if ret is not None:   # 子块里触发了 goto
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

    # 边执行边产出 reply；返回值是一个生成器
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
