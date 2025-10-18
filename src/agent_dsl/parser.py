# src/agent_dsl/parser.py
from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class Action:
    kind: str                 # "reply" | "goto" | "ask" | "set" | "if_goto"
    args: Dict[str, str] = field(default_factory=dict)

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

def _unquote(val: str) -> str:
    val = val.strip()
    if val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    return val

def parse(text: str) -> Program:
    """
    行式 DSL：
      flow <name>
      state <name>
        reply "text with {{var}}"
        ask <var> "prompt"
        set <var> = "value"
        if <var> == "value" goto <state>
        goto <state>
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

        if not cur_state:
            raise ValueError(f"语句必须出现在 state 内部：{line}")

        if line.startswith("reply "):
            val = _unquote(line[len("reply "):])
            cur_state.actions.append(Action(kind="reply", args={"text": val}))
            continue

        if line.startswith("goto "):
            target = line.split(" ", 1)[1].strip()
            cur_state.actions.append(Action(kind="goto", args={"target": target}))
            continue

        if line.startswith("ask "):
            # ask <var> "prompt"
            rest = line[len("ask "):].strip()
            var, prompt = rest.split(" ", 1)
            cur_state.actions.append(Action(kind="ask", args={"var": var, "prompt": _unquote(prompt)}))
            continue

        if line.startswith("set "):
            # set <var> = "value"
            rest = line[len("set "):].strip()
            if "=" not in rest:
                raise ValueError("set 语法：set <var> = \"value\"")
            var, val = rest.split("=", 1)
            cur_state.actions.append(Action(kind="set", args={"var": var.strip(), "value": _unquote(val)}))
            continue

        if line.startswith("if "):
            # if <var> == "value" goto <state>
            rest = line[len("if "):].strip()
            # 非健壮解析，但覆盖我们当前语法即可
            # 拆: <left> == <right> goto <state>
            if " goto " not in rest or "==" not in rest:
                raise ValueError('if 语法：if <var> == "value" goto <state>')
            cond_part, target = rest.split(" goto ", 1)
            left, right = cond_part.split("==", 1)
            cur_state.actions.append(Action(
                kind="if_goto",
                args={"left": left.strip(), "right": _unquote(right), "target": target.strip()}
            ))
            continue

        raise ValueError(f"无法识别的语句：{line}")

    if not prog.flows:
        raise ValueError("至少需要一个 flow")
    return prog
