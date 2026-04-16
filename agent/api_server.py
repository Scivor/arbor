"""
agent/api_server.py
Flask REST API for Coffee V3.0 — Hedge Decision System.

Run:
    cd ~/coffee_v3
    .venv311/bin/python -m agent.api_server
    # or via CLI:
    python coffee.py --server

Endpoints:
    GET  /health              — Health check
    GET  /hedge/status        — Current hedge ratio + position
    POST /hedge/execute       — Execute hedge ratio (paper or live)
    GET  /paper/summary       — Paper trading PnL summary
    POST /research            — Run agent swarm research
    GET  /market/price        — Current KC=F price
    GET  /events/recent       — Recent events from EventBus
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, Future

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from flask import Flask, jsonify, request
from dataclasses import asdict

# ─── App Setup ──────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

_executor = ThreadPoolExecutor(max_workers=3)

# Global agent loop instance (lazy init)
_agent_loop = None
_agent_loop_lock = threading.Lock()

# ─── Helpers ───────────────────────────────────────────────────────────────

def _get_engine():
    """Get or create DecisionEngine singleton."""
    from core.state.engine import DecisionEngine
    if not hasattr(_get_engine, '_engine'):
        _get_engine._engine = DecisionEngine(use_yaml=True)
    return _get_engine._engine


def _get_paper_engine():
    """Get or create PaperTradingEngine singleton."""
    from core.paper_trading import PaperTradingEngine
    if not hasattr(_get_paper_engine, '_engine'):
        _get_paper_engine._engine = PaperTradingEngine(
            db_path='~/.coffee_v3/decisions.db',
            initial_equity=100_000.0,
            monthly_tons=375.0,
        )
    return _get_paper_engine._engine


def _get_price():
    """Fetch current KC=F price."""
    from sources.coffee.yfinance_price import PriceSource
    try:
        src = PriceSource()
        data = src.fetch()
        return {
            'price': getattr(data, 'current', 0) or 0,
            'change_1d_pct': getattr(data, 'change_1d_pct', 0) or 0,
            'high_30d': getattr(data, 'high_30d', None),
            'low_30d': getattr(data, 'low_30d', None),
        }
    except Exception as exc:
        return {'price': 0, 'error': str(exc)}


def _get_agent_loop():
    """Get or create AgentLoop singleton."""
    global _agent_loop
    if _agent_loop is not None:
        return _agent_loop
    with _agent_loop_lock:
        if _agent_loop is not None:
            return _agent_loop

        from agent.src.agent.tools import build_registry
        from agent.src.session import SkillsLoader
        from agent.src.providers.chat import ChatLLM

        os.environ.setdefault('OPENAI_API_KEY', os.environ.get('OPENAI_API_KEY', ''))
        api_key = os.environ.get('OPENAI_API_KEY', '')
        if not api_key:
            raise RuntimeError('OPENAI_API_KEY environment variable not set')

        llm = ChatLLM(
            model='gpt-4o',
            api_key=api_key,
            temperature=0.2,
        )

        skills_loader = SkillsLoader(agent_dir=_ROOT / 'agent')
        registry = build_registry(skills_loader)

        from agent.src.agent.loop import AgentLoop
        _agent_loop = AgentLoop(
            registry=registry,
            llm=llm,
            skills_loader=skills_loader,
            max_iterations=50,
        )
        return _agent_loop


def _run_agent_async(prompt: str) -> dict:
    """Run agent in thread — returns result dict."""
    loop = _get_agent_loop()
    result = loop.run(prompt)
    return result


# ─── Routes ────────────────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    """Health check."""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'mode': 'paper' if os.environ.get('PAPER_MODE', 'true').lower() == 'true' else 'live',
    })


@app.route('/hedge/status', methods=['GET'])
def hedge_status():
    """Current hedge status: ratio, position, events."""
    try:
        engine = _get_engine()
        state = engine.get_state()
        paper = _get_paper_engine()
        paper_summary = paper.get_summary()

        return jsonify({
            'timestamp': datetime.now().isoformat(),
            'hedge_ratio': state.hedge_ratio,
            'ml_signal': state.ml_signal,
            'ml_confidence': state.ml_confidence,
            'ml_bias': state.ml_bias,
            'paper': {
                'mode': paper_summary.get('mode'),
                'open_position': paper_summary.get('open_position'),
                'realized_pnl': paper_summary.get('realized_pnl'),
                'unrealized_pnl': paper_summary.get('unrealized_pnl'),
                'total_pnl': paper_summary.get('total_pnl'),
            },
        })
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.route('/hedge/execute', methods=['POST'])
def hedge_execute():
    """
    Execute a hedge ratio recommendation.

    Body (JSON):
        target_ratio: float (0.0-0.95)
        confidence: float (0.0-1.0)
        rationale: str
        paper: bool (default True)
        events_json: str (optional JSON array string)

    Returns:
        Execution result (paper or live)
    """
    try:
        body = request.get_json() or {}
        target_ratio = float(body.get('target_ratio', 0))
        confidence = float(body.get('confidence', 0.5))
        rationale = str(body.get('rationale', ''))
        paper = bool(body.get('paper', True))
        events_json = json.dumps(body.get('events_json', []))

        if paper:
            from agent.src.tools.hedge_execute_tool import HedgeExecuteTool
            result = HedgeExecuteTool.execute(
                target_ratio=target_ratio,
                confidence=confidence,
                rationale=rationale,
                events_json=events_json,
                paper=True,
                dry_run=False,
            )
            try:
                return jsonify(json.loads(result))
            except json.JSONDecodeError:
                return jsonify({'result': result})
        else:
            # Live trading — not implemented yet
            return jsonify({'error': 'Live trading not implemented'}), 501

    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.route('/paper/summary', methods=['GET'])
def paper_summary():
    """Paper trading summary."""
    try:
        paper = _get_paper_engine()
        summary = paper.get_summary()
        # Convert any non-serializable objects
        def _clean(obj):
            if isinstance(obj, dict):
                return {k: _clean(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [_clean(i) for i in obj]
            elif hasattr(obj, 'isoformat'):
                return obj.isoformat()
            elif isinstance(obj, (int, float, str, bool, type(None))):
                return obj
            else:
                return str(obj)
        return jsonify(_clean(summary))
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.route('/research', methods=['POST'])
def research():
    """
    Run agent swarm research asynchronously.

    Body (JSON):
        prompt: str (research question)
        wait: bool (if True, block until done; default False)

    Returns (202 Accepted if wait=False):
        {"status": "accepted", "task_id": "..."}
    Poll GET /research/<task_id> for results.
    """
    body = request.get_json() or {}
    prompt = str(body.get('prompt', 'Coffee price outlook for next 3 months'))
    wait = bool(body.get('wait', False))

    try:
        api_key = os.environ.get('OPENAI_API_KEY', '')
        if not api_key:
            return jsonify({'error': 'OPENAI_API_KEY not set'}), 500

        if wait:
            # Synchronous — block until done
            loop = _get_agent_loop()
            result = loop.run(prompt)
            return jsonify({
                'status': 'done',
                'result': result.get('content', ''),
                'iterations': result.get('iterations', 0),
            })
        else:
            # Asynchronous — return task_id
            import uuid
            task_id = str(uuid.uuid4())[:8]

            def _background():
                try:
                    loop = _get_agent_loop()
                    result = loop.run(prompt)
                    _research_results[task_id] = {
                        'status': 'done',
                        'result': result.get('content', ''),
                        'iterations': result.get('iterations', 0),
                    }
                except Exception as exc:
                    _research_results[task_id] = {'status': 'error', 'error': str(exc)}

            _research_results[task_id] = {'status': 'running'}
            _executor.submit(_background)
            return jsonify({'status': 'accepted', 'task_id': task_id}), 202

    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


# In-memory task results store (cleared on restart)
_research_results: dict = {}


@app.route('/research/<task_id>', methods=['GET'])
def research_status(task_id: str):
    """Poll research task status / result."""
    result = _research_results.get(task_id)
    if result is None:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify({'task_id': task_id, **result})


@app.route('/market/price', methods=['GET'])
def market_price():
    """Current KC=F price from Yahoo Finance."""
    try:
        price_data = _get_price()
        if 'error' in price_data:
            return jsonify(price_data), 500
        return jsonify({
            'timestamp': datetime.now().isoformat(),
            'symbol': 'KC=F',
            **price_data,
        })
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.route('/events/recent', methods=['GET'])
def events_recent():
    """Recent events from EventBus."""
    try:
        limit = int(request.args.get('limit', 50))
        from core.events.bus import EventBus
        bus = EventBus()
        events = bus.get_recent(limit=limit)
        return jsonify({
            'count': len(events),
            'events': [
                {
                    'timestamp': e.timestamp.isoformat() if hasattr(e.timestamp, 'isoformat') else str(e.timestamp),
                    'type': e.event_type.value if hasattr(e.event_type, 'value') else str(e.event_type),
                    'domain': e.domain.value if hasattr(e.domain, 'value') else str(e.domain),
                    'severity': e.severity,
                    'value': e.value,
                    'narrative': e.narrative,
                }
                for e in reversed(events)
            ],
        })
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


# ─── Main ─────────────────────────────────────────────────────────────────

def run(host: str = '0.0.0.0', port: int = 8080, debug: bool = False):
    """Run the API server."""
    print(f"\n{'='*50}")
    print(f"  Coffee V3.0 API Server")
    print(f"  http://{host}:{port}")
    print(f"{'='*50}")
    print(f"  GET  /health             — Health check")
    print(f"  GET  /hedge/status       — Current hedge status")
    print(f"  POST /hedge/execute      — Execute hedge (paper)")
    print(f"  GET  /paper/summary      — Paper trading summary")
    print(f"  POST /research           — Run agent swarm (async)")
    print(f"  GET  /research/<task>   — Poll research result")
    print(f"  GET  /market/price      — KC=F current price")
    print(f"  GET  /events/recent      — Recent events")
    print(f"{'='*50}\n")
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Coffee V3.0 API Server')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    # Allow PAPER_MODE env var to control default
    if os.environ.get('PAPER_MODE', '').lower() in ('', 'true', '1'):
        os.environ['PAPER_MODE'] = 'true'

    run(host=args.host, port=args.port, debug=args.debug)
