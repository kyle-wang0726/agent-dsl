# src/agent_dsl/runtime.py
from typing import Iterable, Dict, Any, List, Optional, Callable
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

def _to_number(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None

def _compare(a: str, op: str, b: str) -> bool:
    na, nb = _to_number(a), _to_number(b)
    if na is not None and nb is not None:
        # 数字比较（float, float）——Pylance 可精确推断类型
        if op == "==": return na == nb
        if op == "!=": return na != nb
        if op == ">":  return na >  nb
        if op == "<":  return na <  nb
        if op == ">=": return na >= nb
        if op == "<=": return na <= nb
    else:
        # 字符串比较（str, str）
        if op == "==": return a == b
        if op == "!=": return a != b
        if op == ">":  return a >  b
        if op == "<":  return a <  b
        if op == ">=": return a >= b
        if op == "<=": return a <= b
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
                left = str(self.ctx.get(a["left"], ""))
                right = str(a["right"])
                branch: List[Action] = a["then"] if _compare(left, a["op"], right) else (a.get("else") or [])
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

    # 边执行边产出 reply；返回值是一个生成器（Pylance 满意）
    def run_iter(self) -> Iterable[str]:
        guard = 0
        while True:
            guard += 1
            if guard > 2000:
                raise RuntimeError("可能出现死循环")
            state = self.flow.states[self.state_name]

            buffer: List[str] = []
            target = self._exec_actions(state.actions, buffer.append)

            # 按顺序把本 state 产生的输出吐出去
            for line in buffer:
                yield line

            if target is not None:
                if target not in self.flow.states:
                    raise KeyError(f"goto 的目标状态不存在：{target}")
                self.state_name = target
                continue
            break
