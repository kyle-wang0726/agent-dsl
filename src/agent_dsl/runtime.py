# src/agent_dsl/runtime.py
from typing import List
from .parser import Program, Flow

class Engine:
    def __init__(self, program: Program, flow_name: str = "main"):
        if flow_name not in program.flows:
            raise KeyError(f"找不到 flow: {flow_name}")
        self.flow: Flow = program.flows[flow_name]
        if not self.flow.states:
            raise ValueError("该 flow 下没有任何 state")
        # 默认从第一个定义的 state 开始
        self.state_name = next(iter(self.flow.states.keys()))

    def step_all(self) -> List[str]:
        """顺序执行当前状态的动作，遇到 goto 就跳转到目标状态继续，直到没有 goto 为止。"""
        outputs: List[str] = []
        visited_guard = 0
        while True:
            visited_guard += 1
            if visited_guard > 1000:
                raise RuntimeError("可能出现死循环（过多的跳转）")

            state = self.flow.states[self.state_name]
            jumped = False
            for act in state.actions:
                if act.kind == "reply":
                    outputs.append(act.value)
                elif act.kind == "goto":
                    target = act.value
                    if target not in self.flow.states:
                        raise KeyError(f"goto 的目标状态不存在：{target}")
                    self.state_name = target
                    jumped = True
                    break
                else:
                    raise ValueError(f"未知动作：{act.kind}")
            if not jumped:
                break
        return outputs
