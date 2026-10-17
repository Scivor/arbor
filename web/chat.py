"""
web/chat.py
采购顾问追问页渲染 — 纯字符串拼装，无 fastapi 依赖（便于测试）。

风格对齐 web/track_record.py：手写 HTML + 内联 <style> + 原生 JS，
复用 Kami 设计 token（parchment/brand/olive/stone/border），零外部依赖。

默认交付：若有本期简报，直接展示为顾问开场白 + 追问芯片；
对话只用于澄清。
"""

from __future__ import annotations

import html as html_lib
import json
from typing import Optional, Sequence


def build_chat_page(
    briefing: Optional[str] = None,
    suggestions: Optional[Sequence[str]] = None,
    report_date: Optional[str] = None,
) -> str:
    """
    渲染采购顾问追问页（消息列表 + 输入框，fetch POST /api/chat）。

    Args:
        briefing: 本期「采购下一步建议」正文；有则作为顾问开场白。
        suggestions: 追问芯片文案列表。
        report_date: 简报对应周报日期（展示用）。
    """
    from reports.procurement_briefing import DEFAULT_SUGGESTIONS_ZH

    chips = list(suggestions) if suggestions else list(DEFAULT_SUGGESTIONS_ZH)
    chips_json = json.dumps(chips, ensure_ascii=False)
    briefing_json = json.dumps(briefing or "", ensure_ascii=False)
    date_label = html_lib.escape(report_date) if report_date else ""
    date_note = (
        f'<div class="chat-brief-meta">本期简报 · {date_label} '
        f'<a href="/reports/{date_label}/">查看周报</a></div>'
        if report_date else ""
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>采购顾问 · Arbor</title>
<style>
  body {{
    background: #f5f4ed;
    color: #141413;
    font-family: ui-sans-serif, system-ui, -apple-system, "PingFang SC", "Hiragino Sans GB", sans-serif;
    font-size: 14px;
    margin: 0;
  }}
  .chat-wrap {{
    max-width: 210mm;
    margin: 0 auto;
    padding: 32px 14mm 24px;
    display: flex;
    flex-direction: column;
    min-height: 92vh;
  }}
  .chat-hdr {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 18px;
  }}
  .chat-title {{
    font-family: Charter, Georgia, "Source Han Serif SC", "Noto Serif CJK SC", "Songti SC", serif;
    font-size: 22px;
    font-weight: 600;
    color: #141413;
    letter-spacing: 0.3px;
  }}
  .chat-back {{
    font-size: 12px;
    color: #504e49;
    text-decoration: none;
  }}
  .chat-back:hover {{ color: #1B365D; }}
  .chat-list {{
    flex: 1;
    overflow-y: auto;
    padding: 6px 0 14px;
  }}
  .chat-empty {{
    background: #faf9f5;
    border: 1px solid #e8e6dc;
    border-radius: 6px;
    padding: 28px 20px;
    text-align: center;
    color: #6b6a64;
    font-size: 13px;
  }}
  .chat-brief-meta {{
    font-size: 11px;
    color: #6b6a64;
    margin: 0 0 8px 2px;
  }}
  .chat-brief-meta a {{
    color: #1B365D;
    text-decoration: none;
    margin-left: 8px;
  }}
  .chat-msg {{
    max-width: 78%;
    padding: 10px 14px;
    border-radius: 8px;
    margin-bottom: 10px;
    font-size: 13.5px;
    line-height: 1.65;
    white-space: pre-wrap;
    word-break: break-word;
  }}
  .chat-msg.user {{
    margin-left: auto;
    background: #1B365D;
    color: #f5f4ed;
    border-bottom-right-radius: 2px;
  }}
  .chat-msg.assistant {{
    margin-right: auto;
    background: #faf9f5;
    border: 1px solid #e8e6dc;
    color: #141413;
    border-bottom-left-radius: 2px;
  }}
  .chat-msg.briefing {{
    max-width: 92%;
    border-color: #c5cfc0;
    background: #f7f8f2;
  }}
  .chat-msg.pending {{
    color: #6b6a64;
    font-style: italic;
  }}
  .chat-msg.error {{
    color: #8a3b2e;
    border-color: #d8b4ac;
  }}
  .chat-chips {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 4px 0 12px;
  }}
  .chat-chip {{
    border: 1px solid #e8e6dc;
    background: #faf9f5;
    color: #1B365D;
    border-radius: 4px;
    padding: 6px 12px;
    font-size: 12.5px;
    cursor: pointer;
    font-family: inherit;
  }}
  .chat-chip:hover {{ border-color: #1B365D; }}
  .chat-input-row {{
    display: flex;
    gap: 10px;
    align-items: flex-end;
    border-top: 1px solid #e5e3d8;
    padding-top: 14px;
  }}
  .chat-input-row textarea {{
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
  }}
  .chat-input-row textarea:focus {{ border-color: #1B365D; }}
  .chat-input-row button {{
    background: #1B365D;
    color: #f5f4ed;
    border: 0;
    border-radius: 6px;
    padding: 10px 22px;
    font-size: 13px;
    cursor: pointer;
  }}
  .chat-input-row button:disabled {{
    background: #6b6a64;
    cursor: default;
  }}
</style>
</head>
<body>
<div class="chat-wrap">
  <div class="chat-hdr">
    <span class="chat-title">采购顾问</span>
    <a class="chat-back" href="/">← 返回最新周报</a>
  </div>
  <div class="chat-list" id="chatList">
    <div class="chat-empty" id="chatEmpty">追问采购建议，如「这周该不该买」「套保要紧还是松」「到库成本怎么看」</div>
  </div>
  <div class="chat-chips" id="chatChips" hidden></div>
  <div class="chat-input-row">
    <textarea id="chatInput" rows="2" placeholder="追问建议中不清楚的点，回车发送（Shift+Enter 换行）"></textarea>
    <button id="chatSend" type="button">发送</button>
  </div>
</div>
<script>
const list = document.getElementById('chatList');
const input = document.getElementById('chatInput');
const sendBtn = document.getElementById('chatSend');
const emptyHint = document.getElementById('chatEmpty');
const chipsRow = document.getElementById('chatChips');
const INITIAL_BRIEFING = {briefing_json};
const SUGGESTIONS = {chips_json};
const DATE_NOTE_HTML = {json.dumps(date_note, ensure_ascii=False)};
let pending = false;

function getSessionId() {{
  try {{
    let sid = sessionStorage.getItem('arbor_chat_sid');
    if (!sid) {{
      sid = (crypto.randomUUID && crypto.randomUUID()) ||
        ('s' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10));
      sessionStorage.setItem('arbor_chat_sid', sid);
    }}
    return sid;
  }} catch (e) {{
    return 'anon';
  }}
}}

function addBubble(text, cls) {{
  if (emptyHint) emptyHint.style.display = 'none';
  const div = document.createElement('div');
  div.className = 'chat-msg ' + cls;
  div.textContent = text;  // textContent 防注入，换行由 CSS pre-wrap 保留
  list.appendChild(div);
  list.scrollTop = list.scrollHeight;
  return div;
}}

function renderChips() {{
  if (!SUGGESTIONS || !SUGGESTIONS.length) return;
  chipsRow.innerHTML = '';
  SUGGESTIONS.forEach((label) => {{
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'chat-chip';
    btn.textContent = label;
    btn.addEventListener('click', () => {{
      input.value = label;
      send();
    }});
    chipsRow.appendChild(btn);
  }});
  chipsRow.hidden = false;
}}

function seedBriefing() {{
  if (!INITIAL_BRIEFING) {{
    renderChips();
    return;
  }}
  if (DATE_NOTE_HTML) {{
    const meta = document.createElement('div');
    meta.innerHTML = DATE_NOTE_HTML;
    list.insertBefore(meta.firstChild, emptyHint);
  }}
  addBubble(INITIAL_BRIEFING, 'assistant briefing');
  renderChips();
}}

async function send() {{
  const msg = input.value.trim();
  if (!msg || pending) return;
  pending = true;
  sendBtn.disabled = true;
  chipsRow.hidden = true;
  addBubble(msg, 'user');
  input.value = '';
  const thinking = addBubble('顾问思考中…', 'assistant pending');
  try {{
    const resp = await fetch('/api/chat', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{message: msg, session_id: getSessionId()}}),
    }});
    const data = await resp.json();
    thinking.remove();
    if (resp.ok) {{
      addBubble(data.output || '(无回复)', 'assistant');
    }} else {{
      addBubble(data.error || ('请求失败 (' + resp.status + ')'), 'assistant error');
    }}
  }} catch (e) {{
    thinking.remove();
    addBubble('网络错误：' + e.message, 'assistant error');
  }} finally {{
    pending = false;
    sendBtn.disabled = false;
    input.focus();
  }}
}}

sendBtn.addEventListener('click', send);
input.addEventListener('keydown', (e) => {{
  if (e.key === 'Enter' && !e.shiftKey) {{ e.preventDefault(); send(); }}
}});
seedBriefing();
input.focus();
</script>
</body>
</html>"""
