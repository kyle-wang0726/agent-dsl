from dataclasses import dataclass, field
from typing import Dict, List, Any
import re

@dataclass
class Action:
    kind: str
    args: Dict[str, Any] = field(default_factory=dict)

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


_IF_HEAD = re.compile(r'^if\s+(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*\{$')


def _unquote(val: str) -> str:
    val = val.strip()
    if val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    return val


def parse(text: str) -> Program:
    lines = [ln.rstrip() for ln in text.splitlines()]

    prog = Program()
    i = 0
    n = len(lines)

    def parse_block_actions() -> List[Action]:
        nonlocal i
        actions: List[Action] = []
        while i < n:
            raw = lines[i].strip()

            if not raw or raw.startswith("#"):
                i += 1
                continue

            # 支持 "} else {"：作为子块结束标记
            if (
                raw == "}" 
                or raw.startswith("} else")
                or raw.startswith("state ")
                or raw.startswith("flow ")
            ):
                break

            # if-block 头
            m = _IF_HEAD.match(raw)
            if m:
                lhs, op, rhs = m.group(1).strip(), m.group(2), _unquote(m.group(3))
                i += 1

                # THEN 块
                then_actions: List[Action] = []
                if i >= n:
                    raise ValueError("if 后需要 { 块内容 }")

                # 解析 THEN 内容
                while i < n and not lines[i].strip().startswith("}"):
                    sub = parse_block_actions()
                    if sub:
                        then_actions.extend(sub)
                    if i < n and lines[i].strip().startswith("}"):
                        break

                if i >= n:
                    raise ValueError("缺少 if then 的右括号 '}'")

                cur = lines[i].strip()
                if cur == "}":
                    i += 1
                elif cur.startswith("} else"):
                    pass
                else:
                    raise ValueError("缺少 if then 的右括号 '}'")

                # ELSE 块
                else_actions: List[Action] | None = None
                if i < n:
                    look = lines[i].strip()

                    if look.startswith("} else"):     # ✅ 兼容 "} else {" 同行写法
                        # 当前这一行已经同时包含了 then 的 '}' 与 else 的 '{'
                        # 直接跳到 else 块的第一行内容（即下一行）
                        i += 1
                        else_actions = []
                        # 解析 else 内容直到遇到配对的 '}'
                        while i < n and lines[i].strip() != "}":
                            sub = parse_block_actions()
                            if sub:
                                else_actions.extend(sub)
                            if i < n and lines[i].strip() == "}":
                                break
                        if i >= n or lines[i].strip() != "}":
                            raise ValueError("缺少 else 的右括号 '}'")
                        i += 1  # 消费 else 的 '}'

                    elif lines[i].strip().startswith("else"):  # ✅ 兼容 "else {" 或 "else" 换行再 "{"
                        line = lines[i].strip()
                        if line == "else {":
                            i += 1
                        elif line == "else":
                            i += 1
                            if i >= n or lines[i].strip() != "{":
                                raise ValueError("else 后应为 '{'")
                            i += 1
                        else:
                            raise ValueError("else 用法：else { ... }")

                        else_actions = []
                        while i < n and lines[i].strip() != "}":
                            sub = parse_block_actions()
                            if sub:
                                else_actions.extend(sub)
                            if i < n and lines[i].strip() == "}":
                                break
                        if i >= n or lines[i].strip() != "}":
                            raise ValueError("缺少 else 的右括号 '}'")
                        i += 1  # 消费 else 的 '}'


                actions.append(Action(
                    kind="if_block",
                    args={
                        "left": lhs,
                        "op": op,
                        "right": rhs,
                        "then": then_actions,
                        "else": else_actions
                    }
                ))
                continue

            # reply
            if raw.startswith("reply "):
                val = _unquote(raw[len("reply "):])
                actions.append(Action("reply", {"text": val}))
                i += 1
                continue

            # goto
            if raw.startswith("goto "):
                target = raw.split(" ", 1)[1].strip()
                actions.append(Action("goto", {"target": target}))
                i += 1
                continue

            # ask
            if raw.startswith("ask "):
                rest = raw[len("ask "):].strip()
                var, prompt = rest.split(" ", 1)
                actions.append(Action("ask", {"var": var, "prompt": _unquote(prompt)}))
                i += 1
                continue

            # set
            if raw.startswith("set "):
                rest = raw[len("set "):].strip()
                if "=" not in rest:
                    raise ValueError('set 语法: set <var> = "value"')
                var, val = rest.split("=", 1)
                actions.append(Action("set", {"var": var.strip(), "value": _unquote(val)}))
                i += 1
                continue

            # legacy 行内 if
            if raw.startswith("if "):
                rest = raw[len("if "):].strip()
                if " goto " not in rest or "==" not in rest:
                    raise ValueError('if 语法: if <var> == "value" goto <state>')
                cond, target = rest.split(" goto ", 1)
                left, right = cond.split("==", 1)
                actions.append(Action("if_goto", {
                    "left": left.strip(),
                    "right": _unquote(right),
                    "target": target.strip()
                }))
                i += 1
                continue

            # save
            if raw.startswith("save "):
                rest = raw[len("save "):].strip()
                if " to " not in rest:
                    raise ValueError('save 语法: save <var> to "file.json"')
                var, path = rest.split(" to ", 1)
                actions.append(Action("save", {"var": var.strip(), "path": _unquote(path)}))
                i += 1
                continue

            # load
            if raw.startswith("load "):
                rest = raw[len("load "):].strip()
                if " from " not in rest:
                    raise ValueError('load 语法: load <var> from "file.json"')
                var, path = rest.split(" from ", 1)
                actions.append(Action("load", {"var": var.strip(), "path": _unquote(path)}))
                i += 1
                continue

            raise ValueError(f"无法识别的语句：{raw}")

        return actions

    i = 0
    while i < n:
        raw = lines[i].strip()
        if not raw or raw.startswith("#"):
            i += 1
            continue

        if raw.startswith("flow "):
            flow_name = raw.split(" ", 1)[1].strip()
            flow = Flow(flow_name)
            prog.flows[flow_name] = flow
            i += 1
            while i < n:
                ln = lines[i].strip()
                if ln.startswith("state "):
                    st_name = ln.split(" ", 1)[1].strip()
                    i += 1
                    state = State(st_name)
                    state.actions = parse_block_actions()
                    flow.states[st_name] = state
                    continue
                if ln.startswith("flow "):
                    break
                i += 1
            continue

        if raw.startswith("state "):
            raise ValueError("state 必须出现在 flow 内")

        i += 1

    if not prog.flows:
        raise ValueError("至少需要一个 flow")

    return prog
