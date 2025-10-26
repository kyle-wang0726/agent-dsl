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

# 旧：行内 if（保持兼容）
_IF_GOTO = re.compile(r'^if\s+(.+?)==\s*(.+?)\s+goto\s+(.+?)$')

# 新：块式 if/elif/else（按“条件整体”保存，运行期求值）
_IF_HEAD   = re.compile(r'^if\s+(.+?)\s*\{$')
_ELIF_HEAD = re.compile(r'^elif\s+(.+?)\s*\{$')

def _unquote(val: str) -> str:
    v = val.strip()
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    return v

def parse(text: str) -> Program:
    lines = [ln.rstrip() for ln in text.splitlines()]
    prog = Program()
    i = 0
    n = len(lines)

    def parse_block_actions() -> List[Action]:
        """解析直到遇到 '}' 或 下一个 state/flow/elif/else。"""
        nonlocal i
        actions: List[Action] = []
        while i < n:
            raw = lines[i].strip()
            if not raw or raw.startswith("#"):
                i += 1
                continue

            # 子块终止信号
            if (raw == "}" or raw.startswith("} elif") or raw.startswith("} else")
                or raw.startswith("state ") or raw.startswith("flow ")):
                break

            # ---- if/elif/else 链处理为 if_chain ----
            m_if = _IF_HEAD.match(raw)
            if m_if:
                i += 1
                cond_if = m_if.group(1).strip()

                # 解析 then-block
                then_actions: List[Action] = []
                while i < n and not lines[i].strip().startswith("}"):
                    sub = parse_block_actions()
                    if sub:
                        then_actions.extend(sub)
                    if i < n and lines[i].strip().startswith("}"):
                        break
                if i >= n:
                    raise ValueError("缺少 if 的右括号 '}'")

                cur = lines[i].strip()
                if cur == "}":
                    i += 1
                elif cur.startswith("} elif") or cur.startswith("} else"):
                    pass
                else:
                    raise ValueError("缺少 if 的右括号 '}'")

                # 收集 elif
                branches = [{"cond": cond_if, "actions": then_actions}]
                while i < n:
                    look = lines[i].strip()
                    if look.startswith("} elif"):
                        part = look[len("} elif"):].strip()
                        if not part.endswith("{"):
                            raise ValueError("elif 语法错误，应为 `} elif <cond> {`")
                        cond = part[:-1].strip()
                        i += 1
                    else:
                        m2 = _ELIF_HEAD.match(look)
                        if m2:
                            cond = m2.group(1).strip()
                            i += 1
                        else:
                            break

                    elif_actions: List[Action] = []
                    while i < n and not lines[i].strip().startswith("}"):
                        sub = parse_block_actions()
                        if sub:
                            elif_actions.extend(sub)
                        if i < n and lines[i].strip().startswith("}"):
                            break
                    if i >= n:
                        raise ValueError("缺少 elif 的右括号 '}'")
                    if lines[i].strip() == "}":
                        i += 1
                    elif lines[i].strip().startswith("} elif") or lines[i].strip().startswith("} else"):
                        pass
                    else:
                        raise ValueError("缺少 elif 的右括号 '}'")
                    branches.append({"cond": cond, "actions": elif_actions})

                # 可选 else
                else_actions = None
                if i < n:
                    look = lines[i].strip()
                    if look.startswith("} else"):
                        i += 1
                        else_actions = []
                        while i < n and lines[i].strip() != "}":
                            sub = parse_block_actions()
                            if sub:
                                else_actions.extend(sub)
                            if i < n and lines[i].strip() == "}":
                                break
                        if i >= n or lines[i].strip() != "}":
                            raise ValueError("缺少 else 的右括号 '}'")
                        i += 1
                    elif look.startswith("else"):
                        line = look
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
                        i += 1

                actions.append(Action("if_chain", {
                    "branches": branches,
                    "else": else_actions
                }))
                continue

            # ---- 普通语句 ----
            if raw.startswith("reply "):
                val = _unquote(raw[len("reply "):])
                actions.append(Action("reply", {"text": val}))
                i += 1
                continue

            if raw.startswith("goto "):
                target = raw.split(" ", 1)[1].strip()
                actions.append(Action("goto", {"target": target}))
                i += 1
                continue

            if raw.startswith("ask "):
                rest = raw[len("ask "):].strip()
                var, prompt = rest.split(" ", 1)
                actions.append(Action("ask", {"var": var, "prompt": _unquote(prompt)}))
                i += 1
                continue

            if raw.startswith("set "):
                # 新：右侧可以是字符串常量或任意表达式
                rest = raw[len("set "):].strip()
                if "=" not in rest:
                    raise ValueError('set 语法: set <var> = <expr或"字符串">')
                var, rhs = rest.split("=", 1)
                var = var.strip()
                rhs = rhs.strip()
                if rhs.startswith('"') and rhs.endswith('"'):
                    actions.append(Action("set", {"var": var, "value": _unquote(rhs)}))
                else:
                    actions.append(Action("set_expr", {"var": var, "expr": rhs}))
                i += 1
                continue

            # 旧式行内 if_goto（保留兼容）
            m_legacy = _IF_GOTO.match(raw)
            if m_legacy:
                left, right, target = m_legacy.group(1).strip(), _unquote(m_legacy.group(2)), m_legacy.group(3).strip()
                actions.append(Action("if_goto", {"left": left, "right": right, "target": target}))
                i += 1
                continue

            if raw.startswith("save "):
                rest = raw[len("save "):].strip()
                if " to " not in rest:
                    raise ValueError('save 语法: save <var> to "file.json"')
                var, path = rest.split(" to ", 1)
                actions.append(Action("save", {"var": var.strip(), "path": _unquote(path)}))
                i += 1
                continue

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
