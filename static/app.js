// static/app.js
let SESSION_ID = null;

const $ = (sel) => document.querySelector(sel);
const chatEl = $("#chat");
const msgEl = $("#msg");
const dslPathEl = $("#dslPath");
const useLLMEl = $("#useLLM");

function append(role, text) {
  const box = document.createElement("div");
  box.className = `msg ${role}`;
  box.innerText = text;
  chatEl.appendChild(box);
  chatEl.scrollTo({ top: chatEl.scrollHeight, behavior: "smooth" });
}

function renderMessages(msgs) {
  chatEl.innerHTML = "";
  for (const m of msgs) append(m.role, m.text);
}

async function startSession() {
  chatEl.innerHTML = "";
  const dslPath = dslPathEl.value.trim();
  const useLLM = useLLMEl.checked;

  const res = await fetch("/api/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dsl_path: dslPath, use_llm: useLLM })
  });
  const data = await res.json();
  SESSION_ID = data.session_id;

  renderMessages(data.messages);
  // ⚠️ 前端不再手动 append 提示语，提示已由后端加入 messages
}

async function sendMessage() {
  const text = msgEl.value.trim();
  if (!text) return;
  if (!SESSION_ID) return alert("请先启动会话");

  // 发送前将用户消息直接插到画面上，避免网络延迟显得卡
  append("user", text);
  msgEl.value = "";

  const res = await fetch("/api/send", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: SESSION_ID, text })
  });
  const data = await res.json();
  renderMessages(data.messages);
}

$("#btnStart").addEventListener("click", startSession);
$("#btnSend").addEventListener("click", sendMessage);
msgEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});
