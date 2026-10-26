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

from reports.fonts import css_display_stack, css_sans_stack, css_serif_stack


def build_chat_page(
    briefing: Optional[str] = None,
    suggestions: Optional[Sequence[str]] = None,
    report_date: Optional[str] = None,
    agent: Optional[dict] = None,
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
    provider = (agent or {}).get("provider")
    model = (agent or {}).get("model") or ""
    if (agent or {}).get("configured") and provider == "deepseek":
        provider_line = f"DeepSeek · {model}"
    elif (agent or {}).get("configured") and provider:
        provider_line = f"{provider} · {model}"
    else:
        provider_line = "尚未接通 DeepSeek"
    provider_html = html_lib.escape(provider_line)
    date_note = (
        f'<div class="chat-brief-meta">本期简报 · {date_label} '
        f'<a href="/reports/{date_label}/">查看周报</a></div>'
        if report_date else ""
    )
    sans = css_sans_stack()
    serif = css_serif_stack()
    display = css_display_stack()

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
    font-family: {serif};
    font-size: 14px;
    font-weight: 400;
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
    gap: 12px;
  }}
  .chat-brand {{
    display: flex;
    align-items: center;
    gap: 12px;
  }}
  .chat-logo {{
    height: 22px;
    width: auto;
    display: block;
  }}
  .chat-title {{
    font-family: {display};
    font-size: 22px;
    font-weight: 500;
    color: #141413;
    letter-spacing: 0.02em;
  }}
  .chat-provider {{
    display: block;
    margin-top: 2px;
    font-family: {sans};
    font-size: 11px;
    letter-spacing: 0.08em;
    color: #6b6a64;
  }}
  .chat-hdr-actions {{
    display: flex;
    align-items: center;
    gap: 14px;
  }}
  .chat-reset {{
    border: 0;
    background: transparent;
    color: #504e49;
    font-size: 12px;
    cursor: pointer;
    font-family: {sans};
    padding: 0;
  }}
  .chat-reset:hover {{ color: #1B365D; }}
  .chat-back {{
    font-family: {sans};
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
    border: 0;
    border-radius: 6px;
    padding: 22px 20px 18px;
    text-align: left;
    color: #504e49;
    font-size: 13.5px;
    line-height: 1.65;
  }}
  .chat-empty-kicker {{
    font-family: {serif};
    font-size: 18px;
    font-weight: 500;
    color: #141413;
    margin-bottom: 8px;
  }}
  .chat-empty p {{ margin: 0; }}
  .chat-empty-ask {{
    margin-top: 8px;
    color: #6b6a64;
    font-size: 12.5px;
  }}
  .chat-brief-meta {{
    font-family: {sans};
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
    border: 0;
    color: #141413;
    border-bottom-left-radius: 2px;
  }}
  .chat-msg.briefing {{
    max-width: 92%;
    background: #faf9f5;
  }}
  .chat-msg.pending {{
    color: #6b6a64;
    font-style: italic;
  }}
  .chat-msg.error {{
    color: #B53333;
  }}
  .chat-chips {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 4px 0 12px;
  }}
  .chat-chip {{
    border: 0;
    background: #E4ECF5;
    color: #1B365D;
    border-radius: 4px;
    padding: 6px 12px;
    font-size: 12.5px;
    font-family: {sans};
    cursor: pointer;
  }}
  .chat-chip:hover {{ background: #EEF2F7; }}
  .chat-chip:disabled {{
    opacity: 0.45;
    cursor: default;
  }}
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
    border: 0;
    border-radius: 6px;
    background: #faf9f5;
    color: #141413;
    font-family: inherit;
    font-size: 13.5px;
    line-height: 1.5;
    padding: 10px 12px;
    outline: 1px solid #e8e6dc;
    outline-offset: 0;
  }}
  .chat-input-row textarea:focus {{ outline-color: #1B365D; }}
  .chat-input-row button {{
    background: #1B365D;
    color: #f5f4ed;
    border: 0;
    border-radius: 6px;
    padding: 10px 22px;
    font-family: {sans};
    font-size: 13px;
    font-weight: 500;
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
    <div class="chat-brand">
      <img class="chat-logo" src="/static/img/arbor-wordmark-nav.png" alt="Arbor" width="120" height="34" />
      <span class="chat-title">采购顾问<span class="chat-provider">{provider_html}</span></span>
    </div>
    <div class="chat-hdr-actions">
      <button type="button" class="chat-reset" id="chatReset">清空追问</button>
      <a class="chat-back" href="/">← 返回今日</a>
    </div>
  </div>
  <div class="chat-list" id="chatList">
    <div class="chat-empty" id="chatEmpty">
      <div class="chat-empty-kicker">顾问在岗，简报未到</div>
      <p>没有已出版的早报或周报时，我只接问题，不编数字，也不替你下单。早报在每个上海日期冻结，周报在周六出版。</p>
      <p class="chat-empty-ask">可以先点下面的句子。没有简报时，我会老实说还不能回答。</p>
    </div>
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

function newSessionId() {{
  try {{
    const sid = (crypto.randomUUID && crypto.randomUUID()) ||
      ('s' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10));
    sessionStorage.setItem('arbor_chat_sid', sid);
    return sid;
  }} catch (e) {{
    return 'anon-' + Date.now();
  }}
}}

function getSessionId() {{
  try {{
    let sid = sessionStorage.getItem('arbor_chat_sid');
    if (!sid) sid = newSessionId();
    return sid;
  }} catch (e) {{
    return 'anon';
  }}
}}

function resetChat() {{
  if (pending) return;
  newSessionId();
  list.querySelectorAll('.chat-msg').forEach((el) => {{
    if (!el.classList.contains('briefing')) el.remove();
  }});
  if (!INITIAL_BRIEFING && emptyHint) emptyHint.style.display = '';
  renderChips();
  input.value = '';
  input.focus();
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

function setChipsEnabled(on) {{
  chipsRow.querySelectorAll('.chat-chip').forEach((btn) => {{ btn.disabled = !on; }});
}}

async function send() {{
  const msg = input.value.trim();
  if (!msg || pending) return;
  pending = true;
  sendBtn.disabled = true;
  setChipsEnabled(false);
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
    setChipsEnabled(true);
    chipsRow.hidden = false;
    input.focus();
  }}
}}

sendBtn.addEventListener('click', send);
document.getElementById('chatReset').addEventListener('click', resetChat);
input.addEventListener('keydown', (e) => {{
  if (e.key === 'Enter' && !e.shiftKey) {{ e.preventDefault(); send(); }}
}});
seedBriefing();
input.focus();
</script>
</body>
</html>"""


def _provider_line(agent: Optional[dict], lang: str = "zh") -> str:
    provider = (agent or {}).get("provider")
    model = (agent or {}).get("model") or ""
    if (agent or {}).get("configured") and provider == "deepseek":
        return f"DeepSeek · {model}"
    if (agent or {}).get("configured") and provider:
        return f"{provider} · {model}"
    if lang == "en":
        return "Not connected. Answers stay inside the published text."
    return "尚未接通，按已出版的文字回答"


def build_followup_panel(
    report_date: str,
    lang: str = "zh",
    agent: Optional[dict] = None,
) -> str:
    """周报页尾的追问区。不重复贴五段简报，也不自动发问。"""
    from reports.procurement_briefing import DEFAULT_SUGGESTIONS_EN, DEFAULT_SUGGESTIONS_ZH

    en = lang == "en"
    chips = list(DEFAULT_SUGGESTIONS_EN if en else DEFAULT_SUGGESTIONS_ZH)
    title = "Follow up on this issue" if en else "就这一期追问"
    reset = "Clear" if en else "清空追问"
    lead = (
        "Only the points already printed above. Numbers that were not written are not invented."
        if en else
        "只澄清上面已经写过的建议，没写进这期的数字不编。"
    )
    placeholder = "Ask about one point above" if en else "追问上面没写清的一点"
    send = "Send" if en else "发送"
    thinking = "Thinking…" if en else "顾问思考中…"
    date = html_lib.escape(report_date)
    return f"""<section id="followup" class="followup">
  <div class="followup-hdr">
    <h2>{title}</h2>
    <button type="button" class="followup-reset" id="chatReset">{reset}</button>
  </div>
  <p class="followup-lead">{lead}</p>
  <p class="followup-provider">{html_lib.escape(_provider_line(agent, lang))}</p>
  <div class="followup-chips" id="chatChips"></div>
  <div class="followup-list" id="chatList"></div>
  <div class="followup-input">
    <textarea id="chatInput" rows="2" placeholder="{placeholder}"></textarea>
    <button id="chatSend" type="button">{send}</button>
  </div>
</section>
<style>
#followup {{
  max-width: 210mm;
  margin: 0 auto;
  padding: 8px 14mm 48px;
  background: #f5f4ed;
  color: #141413;
  font-family: {css_serif_stack()};
  font-weight: 400;
}}
#followup .followup-hdr {{
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  border-top: 1px solid #e5e3d8;
  padding-top: 28px;
}}
#followup h2 {{
  font-family: {css_serif_stack()};
  font-size: 22px;
  font-weight: 500;
  margin: 0;
}}
#followup .followup-reset {{
  border: 0;
  background: transparent;
  color: #504e49;
  font-size: 12px;
  cursor: pointer;
  font-family: {css_sans_stack()};
  padding: 0;
}}
#followup .followup-lead,
#followup .followup-provider {{
  margin: 8px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: #504e49;
}}
#followup .followup-provider {{
  font-family: {css_sans_stack()};
  font-size: 11px;
  letter-spacing: 0.06em;
  color: #6b6a64;
}}
#followup .followup-chips {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 16px 0 12px;
}}
#followup .chat-chip {{
  border: 0;
  background: #E4ECF5;
  color: #1B365D;
  border-radius: 4px;
  padding: 6px 12px;
  font-size: 12.5px;
  cursor: pointer;
  font-family: {css_sans_stack()};
}}
#followup .chat-chip:disabled {{ opacity: 0.45; cursor: default; }}
#followup .followup-list {{
  max-height: 420px;
  overflow-y: auto;
  margin-bottom: 12px;
}}
#followup .chat-msg {{
  max-width: 78%;
  padding: 10px 14px;
  border-radius: 8px;
  margin-bottom: 10px;
  font-size: 13.5px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}}
#followup .chat-msg.user {{
  margin-left: auto;
  background: #1B365D;
  color: #f5f4ed;
}}
#followup .chat-msg.assistant {{
  margin-right: auto;
  background: #faf9f5;
  border: 0;
}}
#followup .chat-msg.pending {{ color: #6b6a64; font-style: italic; }}
#followup .chat-msg.error {{ color: #B53333; }}
#followup .followup-input {{
  display: flex;
  gap: 10px;
  align-items: flex-end;
}}
#followup textarea {{
  flex: 1;
  resize: none;
  border: 0;
  border-radius: 6px;
  background: #faf9f5;
  color: #141413;
  font-family: inherit;
  font-size: 13.5px;
  line-height: 1.5;
  padding: 10px 12px;
  outline: 1px solid #e8e6dc;
  outline-offset: 0;
}}
#followup textarea:focus {{ outline-color: #1B365D; }}
#followup #chatSend {{
  background: #1B365D;
  color: #f5f4ed;
  border: 0;
  border-radius: 6px;
  padding: 10px 22px;
  font-family: {css_sans_stack()};
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}}
#followup #chatSend:disabled {{ background: #6b6a64; cursor: default; }}
</style>
<script>
const REPORT_DATE = {json.dumps(date)};
const LANG = {json.dumps("en" if en else "zh")};
const SUGGESTIONS = {json.dumps(chips, ensure_ascii=False)};
const THINKING = {json.dumps(thinking)};
const list = document.getElementById('chatList');
const input = document.getElementById('chatInput');
const sendBtn = document.getElementById('chatSend');
const chipsRow = document.getElementById('chatChips');
let pending = false;

function storageKey() {{ return 'arbor_followup_sid_' + REPORT_DATE; }}
function newSessionId() {{
  try {{
    const sid = (crypto.randomUUID && crypto.randomUUID()) ||
      ('s' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10));
    sessionStorage.setItem(storageKey(), sid);
    return sid;
  }} catch (e) {{
    return 'anon-' + Date.now();
  }}
}}
function getSessionId() {{
  try {{
    let sid = sessionStorage.getItem(storageKey());
    if (!sid) sid = newSessionId();
    return sid;
  }} catch (e) {{
    return 'anon';
  }}
}}
function resetChat() {{
  if (pending) return;
  newSessionId();
  list.querySelectorAll('.chat-msg').forEach((el) => el.remove());
  input.value = '';
}}
function addBubble(text, cls) {{
  const div = document.createElement('div');
  div.className = 'chat-msg ' + cls;
  div.textContent = text;
  list.appendChild(div);
  list.scrollTop = list.scrollHeight;
  return div;
}}
function setChipsEnabled(on) {{
  chipsRow.querySelectorAll('.chat-chip').forEach((btn) => {{ btn.disabled = !on; }});
}}
function renderChips() {{
  chipsRow.innerHTML = '';
  SUGGESTIONS.forEach((label) => {{
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'chat-chip';
    btn.textContent = label;
    btn.addEventListener('click', () => {{ input.value = label; send(); }});
    chipsRow.appendChild(btn);
  }});
}}
async function send() {{
  const msg = input.value.trim();
  if (!msg || pending) return;
  pending = true;
  sendBtn.disabled = true;
  setChipsEnabled(false);
  addBubble(msg, 'user');
  input.value = '';
  const thinking = addBubble(THINKING, 'assistant pending');
  try {{
    const resp = await fetch('/api/chat', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{
        message: msg,
        session_id: getSessionId(),
        report_date: REPORT_DATE,
        lang: LANG,
      }}),
    }});
    const data = await resp.json();
    thinking.remove();
    if (resp.ok) addBubble(data.output || '', 'assistant');
    else addBubble(data.error || ('请求失败 (' + resp.status + ')'), 'assistant error');
  }} catch (e) {{
    thinking.remove();
    addBubble(e.message, 'assistant error');
  }} finally {{
    pending = false;
    sendBtn.disabled = false;
    setChipsEnabled(true);
  }}
}}
sendBtn.addEventListener('click', send);
document.getElementById('chatReset').addEventListener('click', resetChat);
input.addEventListener('keydown', (e) => {{
  if (e.key === 'Enter' && !e.shiftKey) {{ e.preventDefault(); send(); }}
}});
renderChips();
</script>"""


def build_followup_note(latest: str, lang: str = "zh") -> str:
    """过刊不放输入框，只指向最新一期的页尾。"""
    date = html_lib.escape(latest)
    href = f"/reports/{date}/?lang=en#followup" if lang == "en" else f"/reports/{date}/#followup"
    if lang == "en":
        text = f'Follow-up stays on the <a href="{href}">latest issue</a>.'
    else:
        text = f'追问只挂在<a href="{href}">最新一期</a>。'
    return f'<p class="followup-note" style="max-width:210mm;margin:0 auto;padding:12px 14mm 36px;font-size:13px;color:#504e49;">{text}</p>'


def build_followup_waiting(agent: Optional[dict] = None, lang: str = "zh") -> str:
    """还没有周报时，/chat/ 不装一间顾问室。"""
    if lang == "en":
        title = "Follow-up"
        body = "The follow-up waits for the weekly report. This week has none yet."
        back = "Back home"
        home = "/?lang=en"
    else:
        title = "追问"
        body = "追问在周报页尾。这周还没有周报。"
        back = "返回首页"
        home = "/"
    provider = html_lib.escape(_provider_line(agent, lang))
    return f"""<!DOCTYPE html>
<html lang="{'en' if lang == 'en' else 'zh-CN'}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} · Arbor</title>
</head>
<body style="background:#f5f4ed;color:#141413;font-family:{css_serif_stack()};font-weight:400;margin:0;">
<main style="max-width:640px;margin:0 auto;padding:72px 24px;">
  <h1 style="font-family:{css_serif_stack()};font-size:28px;font-weight:500;letter-spacing:0.02em;">{title}</h1>
  <p style="line-height:1.7;color:#504e49;">{body}</p>
  <p style="font-family:{css_sans_stack()};font-size:12px;color:#6b6a64;">{provider}</p>
  <p><a href="{home}" style="font-family:{css_sans_stack()};color:#1B365D;text-decoration:none;">{back}</a></p>
</main>
</body>
</html>"""
