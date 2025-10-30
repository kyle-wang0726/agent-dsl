from __future__ import annotations
import uuid
from pathlib import Path
from typing import Dict, Optional, List, Callable

from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .parser import parse
from .runtime import Engine

# ========= 路径 =========
ROOT_DIR = Path(__file__).resolve().parents[2]   # 项目根
TEMPLATES_DIR = ROOT_DIR / "templates"
STATIC_DIR = ROOT_DIR / "static"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"])
)

# ========= 中断异常：用于在下一次 ask 前停下 =========
class NeedMoreInput(Exception):
    def __init__(self, var: str, prompt: str):
        super().__init__(f"Need input for {var}")
        self.var = var
        self.prompt = prompt

# ========= FastAPI =========
app = FastAPI(title="Agent-DSL Web UI")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
else:
    print(f"[WebApp] ⚠ static 目录不存在：{STATIC_DIR}")

# ========= 会话 =========
class SessionState:
    def __init__(self, program_text: str, dsl_path: str, use_llm: bool):
        self.program_text = program_text
        self.dsl_path = dsl_path
        self.use_llm = use_llm
        self.program = parse(program_text)
        self.engine: Engine = self._create_engine([])
        self.chat: List[Dict] = []           # {"role": "assistant"/"user", "text": "..."}
        self.await_var: Optional[str] = None
        self.await_prompt: Optional[str] = None

    def _make_ask_fn(self, inputs: List[str]) -> Callable[[str, str], str]:
        """第一次返回 inputs[0]；否则抛 NeedMoreInput 让前端提示下一步输入。"""
        called = {"n": 0}
        def ask(var: str, prompt: str) -> str:
            called["n"] += 1
            if called["n"] == 1 and inputs:
                return inputs[0]
            raise NeedMoreInput(var, prompt)
        return ask

    def _create_engine(self, inputs: List[str]) -> Engine:
        return Engine(
            program=self.program,
            flow_name="main",
            context=None,
            ask_fn=self._make_ask_fn(inputs),
            debug=False,
            use_llm=self.use_llm,
            printer=lambda s: None,   # 在 step() 里覆盖为收集函数
        )

    def step(self, user_text: Optional[str]) -> Dict:
        """
        推进一次：
        - 若提供 user_text 则作为本轮第一个 ask 的回答
        - 返回 messages / await / ended
        """
        msgs: List[str] = []

        # 覆盖引擎的 printer：把 ask 前冲洗出来的 reply 收集到 msgs
        self.engine.printer = lambda s: msgs.append(s)

        # 记录用户发言
        if user_text is not None:
            self.chat.append({"role": "user", "text": user_text})

        # 更新 ask_fn
        inputs = [user_text] if user_text is not None else []
        self.engine.ask_fn = self._make_ask_fn(inputs)

        try:
            for out in self.engine.run_iter():
                msgs.append(out)
        except NeedMoreInput as e:
            # 在会话里也保留 prompt，这样前端不会“下一轮被覆盖丢失”
            self.await_var = e.var
            self.await_prompt = e.prompt
            msgs.append(e.prompt)  # 把提示作为一条助手消息写入
        else:
            self.await_var = None
            self.await_prompt = None

        # —— 关键去重：如果本轮第一条助手消息与历史最后一条助手消息重复，丢弃它 ——
        if (
            msgs
            and self.chat
            and self.chat[-1]["role"] == "assistant"
            and msgs[0] == self.chat[-1]["text"]
        ):
            msgs = msgs[1:]

        # 写入新产生的助手消息
        for m in msgs:
            self.chat.append({"role": "assistant", "text": m})

        return {
            "messages": [{"role": m["role"], "text": m["text"]} for m in self.chat[-200:]],
            "await": None if self.await_var is None else {"var": self.await_var, "prompt": self.await_prompt},
            "ended": self.await_var is None and not msgs and self.engine.state_name not in self.engine.flow.states,
        }

# 全局会话表
SESSIONS: Dict[str, SessionState] = {}

# ========= 路由 =========
@app.get("/", response_class=HTMLResponse)
def index():
    if not TEMPLATES_DIR.exists():
        return HTMLResponse("<h1>⚠ templates 目录不存在</h1>", status_code=500)
    tpl = env.get_template("index.html")
    return tpl.render()

@app.post("/api/start")
async def api_start(request: Request):
    data = await request.json()
    dsl_path = data.get("dsl_path", "examples/customer.dsl")
    use_llm = bool(data.get("use_llm", False))

    path = ROOT_DIR / dsl_path
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"DSL 文件不存在: {dsl_path}")

    program_text = path.read_text(encoding="utf-8")
    sid = uuid.uuid4().hex
    SESSIONS[sid] = SessionState(program_text, dsl_path, use_llm)
    payload = SESSIONS[sid].step(user_text=None)   # 首次推进，欢迎语 + 首个 ask 提示
    return JSONResponse({"session_id": sid, **payload})

@app.post("/api/send")
async def api_send(request: Request):
    data = await request.json()
    sid = data.get("session_id")
    text = data.get("text", "")

    if not sid or sid not in SESSIONS:
        raise HTTPException(status_code=400, detail="无效的会话，请先启动会话。")

    payload = SESSIONS[sid].step(user_text=text)
    return JSONResponse({"session_id": sid, **payload})
