"""
web/chat.py
AI 分析师聊天页渲染 — 纯字符串拼装，无 fastapi 依赖（便于测试）。

风格对齐 web/track_record.py：手写 HTML + 内联 <style> + 原生 JS，
复用 Kami 设计 token（parchment/brand/olive/stone/border），零外部依赖。
"""

from __future__ import annotations


def build_chat_page() -> str:
    """渲染 AI 分析师聊天页（消息列表 + 输入框，fetch POST /api/chat）。"""
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI 分析师 · Arbor</title>
<style>
  body {
    background: #f5f4ed;
    color: #141413;
    font-family: ui-sans-serif, system-ui, -apple-system, "PingFang SC", "Hiragino Sans GB", sans-serif;
    font-size: 14px;
    margin: 0;
  }
  .chat-wrap {
    max-width: 210mm;
    margin: 0 auto;
    padding: 32px 14mm 24px;
    display: flex;
    flex-direction: column;
    min-height: 92vh;
  }
  .chat-hdr {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 18px;
  }
  .chat-title {
    font-family: Charter, Georgia, "Source Han Serif SC", "Noto Serif CJK SC", "Songti SC", serif;
    font-size: 22px;
    font-weight: 600;
    color: #141413;
    letter-spacing: 0.3px;
  }
  .chat-back {
    font-size: 12px;
    color: #504e49;
    text-decoration: none;
  }
  .chat-back:hover { color: #1B365D; }
  .chat-list {
    flex: 1;
    overflow-y: auto;
    padding: 6px 0 14px;
  }
  .chat-empty {
    background: #faf9f5;
    border: 1px solid #e8e6dc;
    border-radius: 6px;
    padding: 28px 20px;
    text-align: center;
    color: #6b6a64;
    font-size: 13px;
  }
  .chat-msg {
    max-width: 78%;
    padding: 10px 14px;
    border-radius: 8px;
    margin-bottom: 10px;
    font-size: 13.5px;
    line-height: 1.65;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .chat-msg.user {
    margin-left: auto;
    background: #1B365D;
    color: #f5f4ed;
    border-bottom-right-radius: 2px;
  }
  .chat-msg.assistant {
    margin-right: auto;
    background: #faf9f5;
    border: 1px solid #e8e6dc;
    color: #141413;
    border-bottom-left-radius: 2px;
  }
  .chat-msg.pending {
    color: #6b6a64;
    font-style: italic;
  }
  .chat-msg.error {
    color: #8a3b2e;
    border-color: #d8b4ac;
  }
  .chat-input-row {
    display: flex;
    gap: 10px;
    align-items: flex-end;
    border-top: 1px solid #e5e3d8;
    padding-top: 14px;
  }
  .chat-input-row textarea {
    flex: 1;
    resize: none;
    border: 1px solid #e8e6dc;
    border-radius: 6px;
    background: #faf9f5;
    color: #141413;
    font-family: inherit;
    font-size: 13.5px;
    line-height: 1.5;
    padding: 10px 12px;
    outline: none;
  }
  .chat-input-row textarea:focus { border-color: #1B365D; }
  .chat-input-row button {
    background: #1B365D;
    color: #f5f4ed;
    border: 0;
    border-radius: 6px;
    padding: 10px 22px;
    font-size: 13px;
    cursor: pointer;
  }
  .chat-input-row button:disabled {
    background: #6b6a64;
    cursor: default;
  }
</style>
</head>
<body>
<div class="chat-wrap">
  <div class="chat-hdr">
    <span class="chat-title">AI 分析师</span>
    <a class="chat-back" href="/">← 返回最新周报</a>
  </div>
  <div class="chat-list" id="chatList">
    <div class="chat-empty" id="chatEmpty">向分析师提问，如「咖啡怎么看」「当前套保建议合理吗」</div>
  </div>
  <div class="chat-input-row">
    <textarea id="chatInput" rows="2" placeholder="输入问题，回车发送（Shift+Enter 换行）"></textarea>
    <button id="chatSend" type="button">发送</button>
  </div>
</div>
<script>
const list = document.getElementById('chatList');
const input = document.getElementById('chatInput');
const sendBtn = document.getElementById('chatSend');
const emptyHint = document.getElementById('chatEmpty');
let pending = false;

function addBubble(text, cls) {
  if (emptyHint) emptyHint.style.display = 'none';
  const div = document.createElement('div');
  div.className = 'chat-msg ' + cls;
  div.textContent = text;  // textContent 防注入，换行由 CSS pre-wrap 保留
  list.appendChild(div);
  list.scrollTop = list.scrollHeight;
  return div;
}

async function send() {
  const msg = input.value.trim();
  if (!msg || pending) return;
  pending = true;
  sendBtn.disabled = true;
  addBubble(msg, 'user');
  input.value = '';
  const thinking = addBubble('分析师思考中…', 'assistant pending');
  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg}),
    });
    const data = await resp.json();
    thinking.remove();
    if (resp.ok) {
      addBubble(data.output || '(无回复)', 'assistant');
    } else {
      addBubble(data.error || ('请求失败 (' + resp.status + ')'), 'assistant error');
    }
  } catch (e) {
    thinking.remove();
    addBubble('网络错误：' + e.message, 'assistant error');
  } finally {
    pending = false;
    sendBtn.disabled = false;
    input.focus();
  }
}

sendBtn.addEventListener('click', send);
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
input.focus();
</script>
</body>
</html>"""
