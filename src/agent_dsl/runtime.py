# src/agent_dsl/runtime.py
from typing import List, Dict, Iterable
import re
from .parser import Program, Flow, Action

_VAR_PATTERN = re.compile(r"\{\{(\w+)\}\}")

def _interpolate(s: str, ctx: Dict[str, str]) -> str:
    def repl(m):
        key = m.group(1)
        return str(ctx.get(key, f"{{{{{key}}}}}"))
    return _VAR_PATTERN.sub(repl, s)

class Engine:
    def __init__(self, program: Program, flow_name: str = "main",
                 context: Dict[str, str] | None = None, ask_fn=None):
        if flow_name not in program.flows:
            raise KeyError(f"找不到 flow: {flow_name}")
        self.flow: Flow = program.flows[flow_name]
        if not self.flow.states:
            raise ValueError("该 flow 下没有任何 state")
        self.state_name = next(iter(self.flow.states.keys()))
        self.ctx: Dict[str, str] = dict(context or {})
        self.ask_fn = ask_fn

    # ✅ 新增：边执行边产出 reply
    def run_iter(self) -> Iterable[str]:
        visited_guard = 0
        while True:
            visited_guard += 1
            if visited_guard > 2000:
                raise RuntimeError("可能出现死循环（过多跳转）")

            state = self.flow.states[self.state_name]
            jumped = False
            for act in state.actions:
                k = act.kind
                a = act.args
                if k == "reply":
                    yield _interpolate(a["text"], self.ctx)
                elif k == "set":
                    self.ctx[a["var"]] = a["value"]
                elif k == "ask":
                    var, prompt = a["var"], a["prompt"]
                    if var not in self.ctx:
                        if self.ask_fn:
                            self.ctx[var] = self.ask_fn(var, prompt)
                        else:
                            self.ctx[var] = input(prompt)
                elif k == "if_goto":
                    left = self.ctx.get(a["left"], "")
                    right = a["right"]
                    if str(left) == str(right):
                        target = a["target"]
                        if target not in self.flow.states:
                            raise KeyError(f"goto 的目标状态不存在：{target}")
                        self.state_name = target
                        jumped = True
                        break
                elif k == "goto":
                    target = a["target"]
                    if target not in self.flow.states:
                        raise KeyError(f"goto 的目标状态不存在：{target}")
                    self.state_name = target
                    jumped = True
                    break
                else:
                    raise ValueError(f"未知动作：{k}")

            if not jumped:
                break
