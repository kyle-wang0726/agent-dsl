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

# ====== 通用表达式求值（数值/字符串），安全子集 ======
_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)
_ALLOWED_UNARY  = (ast.UAdd, ast.USub)

def _coerce_number(v: Any) -> Any:
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v)
    try:
        return float(s)
    except Exception:
        return v

def _eval_value_node(node: ast.AST, ctx: Dict[str, str]) -> Any:
    """数值/字符串表达式求值：常量、变量、()、+ - * / // %、一元±。"""
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
        # 允许字符串相加
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
        return ctx.get(node.id, "")
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Subscript) or isinstance(node, ast.Call) or isinstance(node, ast.Attribute):
        raise ValueError("不允许下标/调用/属性访问")
    # 允许括号（由 Expression/子节点处理）
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

# ====== 新：布尔表达式求值（and/or/not、比较链） ======
def _eval_bool(expr: str, ctx: Dict[str, str]) -> bool:
    tree = ast.parse(expr, mode="eval")

    def ev(node: ast.AST) -> bool:
        if isinstance(node, ast.Expression):
            return ev(node.body)

        # and / or（短路）
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                # 所有值都为 True 才 True
                for v in node.values:
                    if not ev(v):
                        return False
                return True
            if isinstance(node.op, ast.Or):
                # 有一个 True 即 True
                for v in node.values:
                    if ev(v):
                        return True
                return False
            raise ValueError("仅支持 and / or")

        # not
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not ev(node.operand)

        # 比较：支持链式 a < b < c
        if isinstance(node, ast.Compare):
            left_val = _eval_value_node(node.left, ctx)
            cur = left_val
            for op, comp in zip(node.ops, node.comparators):
                right_val = _eval_value_node(comp, ctx)
                if isinstance(op, ast.Eq):    ok = _do_compare(cur, "==", right_val)
                elif isinstance(op, ast.NotEq): ok = _do_compare(cur, "!=", right_val)
                elif isinstance(op, ast.Gt):    ok = _do_compare(cur, ">",  right_val)
                elif isinstance(op, ast.Lt):    ok = _do_compare(cur, "<",  right_val)
                elif isinstance(op, ast.GtE):   ok = _do_compare(cur, ">=", right_val)
                elif isinstance(op, ast.LtE):   ok = _do_compare(cur, "<=", right_val)
                else:
                    raise ValueError("比较运算仅支持 == != > < >= <=")
                if not ok:
                    return False
                cur = right_val
            return True

        # 允许把“值”的真值当作布尔（不推荐写法，但不禁止）
        if isinstance(node, (ast.Constant, ast.Name, ast.BinOp, ast.UnaryOp)):
            v = _eval_value_node(node, ctx)
            if isinstance(v, (int, float)):
                return v != 0
            return bool(v)

        raise ValueError(f"不允许的布尔表达式：{ast.dump(node, include_attributes=False)}")

    return ev(tree)

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

            elif k == "if_chain":
                # 依次判断各分支（短路）
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
                branch: List[Action] = a["then"] if _do_compare(left_val, a["op"], right_val) \
                                       else (a.get("else") or [])
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
