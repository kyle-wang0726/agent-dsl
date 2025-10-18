# src/agent_dsl/parser.py
from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class Action:
    kind: str                # "reply" | "goto"
    value: str               # text or target state

@dataclass
class State:
    name: str
    actions: List[Action] = field(default_factory=list)

@dataclass
class Flow:
    name: str
    states: Dict[str, State] = field(default_factory=dict)

@dataclass
class Program:
    flows: Dict[str, Flow] = field(default_factory=dict)

def parse(text: str) -> Program:
    """
    极简行式 DSL 解析器：
      flow <name>
      state <name>
        reply "text"
        goto <state-name>
    """
    prog = Program()
    cur_flow: Flow | None = None
    cur_state: State | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("flow "):
            name = line.split(" ", 1)[1].strip()
            cur_flow = Flow(name=name)
            prog.flows[name] = cur_flow
            cur_state = None
            continue

        if line.startswith("state "):
            if not cur_flow:
                raise ValueError("state 必须出现在 flow 内部")
            name = line.split(" ", 1)[1].strip()
            cur_state = State(name=name)
            cur_flow.states[name] = cur_state
            continue

        if line.startswith("reply "):
            if not cur_state:
                raise ValueError("reply 必须出现在 state 内部")
            # 支持 reply "xxx"
            val = line[len("reply "):].strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            cur_state.actions.append(Action(kind="reply", value=val))
            continue

        if line.startswith("goto "):
            if not cur_state:
                raise ValueError("goto 必须出现在 state 内部")
            target = line.split(" ", 1)[1].strip()
            cur_state.actions.append(Action(kind="goto", value=target))
            continue

        raise ValueError(f"无法识别的语句：{line}")

    if not prog.flows:
        raise ValueError("至少需要一个 flow")
    return prog
