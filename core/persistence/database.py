"""
core/persistence/database.py
DecisionDB — SQLite persistence layer.

Tables:
  - decisions       : hedge adjustment decisions
  - hedge_trades    : futures trade records
  - equity_snapshots: daily equity snapshots
  - events          : market events
  - hedge_signals   : daily hedge signals
"""

from __future__ import annotations
import sqlite3
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

# Schema as a string constant (not a file dependency)
SCHEMA_SQL = '''
    CREATE TABLE IF NOT EXISTS decisions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT NOT NULL,
        event_type      TEXT,
        severity        INTEGER,
        event_narrative TEXT,
        prev_ratio      REAL,
        target_ratio    REAL,
        action          TEXT,
        price           REAL,
        hedge_tons      REAL,
        narrative       TEXT,
        source          TEXT
    );

    CREATE TABLE IF NOT EXISTS hedge_trades (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_time      TEXT,
        exit_time       TEXT,
        entry_price     REAL,
        exit_price      REAL,
        size_tons       REAL,
        hedge_ratio     REAL,
        action          TEXT,
        pnl             REAL,
        pnl_pct         REAL,
        exit_reason     TEXT,
        holding_days    INTEGER,
        commission      REAL,
        narrative       TEXT,
        is_paper        INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS equity_snapshots (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT NOT NULL,
        price           REAL,
        equity          REAL,
        hedge_ratio     REAL,
        hedge_pnl       REAL,
        contracts       INTEGER,
        oni             REAL,
        ice_inventory   REAL,
        cot_net         REAL,
        spec_net        REAL
    );

    CREATE TABLE IF NOT EXISTS events (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT NOT NULL,
        event_type      TEXT NOT NULL,
        severity        INTEGER,
        narrative       TEXT,
        source          TEXT,
        resolved        INTEGER DEFAULT 0,
        resolution_ts   TEXT
    );

    CREATE TABLE IF NOT EXISTS hedge_signals (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT NOT NULL,
        oni_phase       TEXT,
        ice_inventory   REAL,
        cot_net         REAL,
        spec_net        REAL,
        price           REAL,
        price_rank      REAL,
        volatility      REAL,
        frost_season    INTEGER,
        signal_type     TEXT,
        target_ratio    REAL,
        severity        INTEGER,
        triggered       INTEGER DEFAULT 0
    );

    CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(timestamp);
    CREATE INDEX IF NOT EXISTS idx_trades_entry  ON hedge_trades(entry_time);
    CREATE INDEX IF NOT EXISTS idx_equity_ts     ON equity_snapshots(timestamp);
    CREATE INDEX IF NOT EXISTS idx_events_ts     ON events(timestamp);
    CREATE INDEX IF NOT EXISTS idx_signals_ts    ON hedge_signals(timestamp);
'''


class DecisionDB:
    """
    Coffee hedge decision database.

    Usage:
        db = DecisionDB('~/.arbor/decisions.db')
        db.save_decision(event_type, prev_ratio, target_ratio, ...)
        db.save_trade(entry_time, exit_time, entry_price, ...)
        df = db.get_equity_curve()
    """

    def __init__(self, path: str | Path = '~/.arbor/decisions.db'):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript(SCHEMA_SQL)
        conn.commit()

        # Migration: add is_paper column to hedge_trades if missing
        try:
            conn.execute("ALTER TABLE hedge_trades ADD COLUMN is_paper INTEGER DEFAULT 0")
            conn.commit()
        except Exception:
            pass  # Column already exists

    # ─── Decisions ────────────────────────────────────────────────────────────

    def save_decision(
        self,
        event_type: str,
        prev_ratio: float,
        target_ratio: float,
        action: str,
        price: float,
        hedge_tons: float,
        severity: int = 0,
        event_narrative: str = '',
        narrative: str = '',
        source: str = 'manual',
        timestamp: Optional[str] = None,
    ):
        """Save a hedge adjustment decision."""
        ts = timestamp or datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute('''
            INSERT INTO decisions
                (timestamp, event_type, severity, event_narrative,
                 prev_ratio, target_ratio, action, price, hedge_tons, narrative, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (ts, event_type, severity, event_narrative,
              prev_ratio, target_ratio, action, price, hedge_tons, narrative, source))
        conn.commit()

    def get_decisions(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 100,
    ) -> pd.DataFrame:
        """Query decision history."""
        conn = self._get_conn()
        query = 'SELECT * FROM decisions WHERE 1=1'
        params = []
        if start:
            query += ' AND timestamp >= ?'
            params.append(start)
        if end:
            query += ' AND timestamp <= ?'
            params.append(end)
        query += ' ORDER BY timestamp DESC LIMIT ?'
        params.append(limit)
        return pd.read_sql_query(query, conn, params=params)

    # ─── Trades ───────────────────────────────────────────────────────────────

    def save_trade(
        self,
        entry_time: str,
        exit_time: str,
        entry_price: float,
        exit_price: float,
        size_tons: float,
        hedge_ratio: float,
        action: str,
        pnl: float,
        pnl_pct: float,
        exit_reason: str,
        holding_days: int,
        commission: float,
        narrative: str = '',
        is_paper: bool = False,
    ):
        """Save a futures trade record."""
        conn = self._get_conn()
        conn.execute('''
            INSERT INTO hedge_trades
                (entry_time, exit_time, entry_price, exit_price, size_tons,
                 hedge_ratio, action, pnl, pnl_pct, exit_reason, holding_days,
                 commission, narrative, is_paper)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (entry_time, exit_time, entry_price, exit_price, size_tons,
              hedge_ratio, action, pnl, pnl_pct, exit_reason, holding_days,
              commission, narrative, int(is_paper)))
        conn.commit()

    def get_trades(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = 500,
        is_paper: Optional[bool] = None,
    ) -> pd.DataFrame:
        """Query trade history."""
        conn = self._get_conn()
        query = 'SELECT * FROM hedge_trades WHERE 1=1'
        params = []
        if start:
            query += ' AND entry_time >= ?'
            params.append(start)
        if end:
            query += ' AND entry_time <= ?'
            params.append(end)
        if is_paper is not None:
            query += ' AND is_paper = ?'
            params.append(int(is_paper))
        query += ' ORDER BY entry_time DESC LIMIT ?'
        params.append(limit)
        return pd.read_sql_query(query, conn, params=params)

    def get_trade_summary(self, is_paper: Optional[bool] = None) -> dict:
        """Trade summary statistics. Optionally filter by paper/live."""
        conn = self._get_conn()
        where = f'WHERE 1=1{" AND is_paper = " + str(int(is_paper)) if is_paper is not None else ""}'
        cur = conn.execute(f'''
            SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(pnl) as total_pnl,
                AVG(pnl) as avg_pnl,
                SUM(commission) as total_commission
            FROM hedge_trades
            {where}
        ''')
        row = cur.fetchone()
        if row['total_trades'] == 0:
            return {'total_trades': 0, 'win_rate': 0, 'total_pnl': 0}
        return {
            'total_trades': row['total_trades'],
            'win_rate': row['wins'] / row['total_trades'],
            'total_pnl': row['total_pnl'],
            'avg_pnl': row['avg_pnl'],
            'total_commission': row['total_commission'],
        }

    def get_paper_summary(self) -> dict:
        """Paper trading summary (is_paper=1 trades only)."""
        live = self.get_trade_summary(is_paper=False)
        paper = self.get_trade_summary(is_paper=True)
        return {'live': live, 'paper': paper}

    # ─── Equity Snapshots ────────────────────────────────────────────────────

    def save_equity_snapshot(
        self,
        price: float,
        equity: float,
        hedge_ratio: float,
        hedge_pnl: float,
        contracts: int,
        oni: Optional[float] = None,
        ice_inventory: Optional[float] = None,
        cot_net: Optional[float] = None,
        spec_net: Optional[float] = None,
        timestamp: Optional[str] = None,
    ):
        """Save a daily equity snapshot."""
        ts = timestamp or datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute('''
            INSERT INTO equity_snapshots
                (timestamp, price, equity, hedge_ratio, hedge_pnl, contracts,
                 oni, ice_inventory, cot_net, spec_net)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (ts, price, equity, hedge_ratio, hedge_pnl, contracts,
              oni, ice_inventory, cot_net, spec_net))
        conn.commit()

    def get_equity_curve(self, start: Optional[str] = None, limit: int = 5000) -> pd.DataFrame:
        """Get equity curve."""
        conn = self._get_conn()
        query = 'SELECT * FROM equity_snapshots WHERE 1=1'
        params = []
        if start:
            query += ' AND timestamp >= ?'
            params.append(start)
        query += ' ORDER BY timestamp LIMIT ?'
        params.append(limit)
        df = pd.read_sql_query(query, conn, params=params)
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
        return df

    # ─── Events ───────────────────────────────────────────────────────────────

    def save_event(
        self,
        event_type: str,
        severity: int,
        narrative: str,
        source: str = 'system',
        timestamp: Optional[str] = None,
    ):
        """Save a market event."""
        ts = timestamp or datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute('''
            INSERT INTO events (timestamp, event_type, severity, narrative, source)
            VALUES (?, ?, ?, ?, ?)
        ''', (ts, event_type, severity, narrative, source))
        conn.commit()

    def resolve_event(self, event_id: int, resolution: str = ''):
        """Mark an event as resolved."""
        conn = self._get_conn()
        conn.execute('''
            UPDATE events SET resolved = 1, resolution_ts = ?
            WHERE id = ?
        ''', (datetime.now().isoformat(), event_id))
        conn.commit()

    def get_events(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        event_type: Optional[str] = None,
        unresolve_only: bool = False,
        limit: int = 100,
    ) -> pd.DataFrame:
        """Query event history."""
        conn = self._get_conn()
        query = 'SELECT * FROM events WHERE 1=1'
        params = []
        if start:
            query += ' AND timestamp >= ?'
            params.append(start)
        if end:
            query += ' AND timestamp <= ?'
            params.append(end)
        if event_type:
            query += ' AND event_type = ?'
            params.append(event_type)
        if unresolve_only:
            query += ' AND resolved = 0'
        query += ' ORDER BY timestamp DESC LIMIT ?'
        params.append(limit)
        return pd.read_sql_query(query, conn, params=params)

    # ─── Signals ─────────────────────────────────────────────────────────────

    def save_signal(
        self,
        target_ratio: float,
        signal_type: str,
        severity: int,
        price: float,
        oni_phase: str = 'NEUTRAL',
        ice_inventory: Optional[float] = None,
        cot_net: Optional[float] = None,
        spec_net: Optional[float] = None,
        price_rank: Optional[float] = None,
        volatility: Optional[float] = None,
        frost_season: bool = False,
        timestamp: Optional[str] = None,
    ):
        """Save a daily hedge signal."""
        ts = timestamp or datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute('''
            INSERT INTO hedge_signals
                (timestamp, oni_phase, ice_inventory, cot_net, spec_net,
                 price, price_rank, volatility, frost_season,
                 signal_type, target_ratio, severity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (ts, oni_phase, ice_inventory, cot_net, spec_net,
              price, price_rank, volatility, int(frost_season),
              signal_type, target_ratio, severity))
        conn.commit()

    def get_signals(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        min_severity: int = 0,
        limit: int = 100,
    ) -> pd.DataFrame:
        """Query signal history."""
        conn = self._get_conn()
        query = 'SELECT * FROM hedge_signals WHERE 1=1'
        params = []
        if start:
            query += ' AND timestamp >= ?'
            params.append(start)
        if end:
            query += ' AND timestamp <= ?'
            params.append(end)
        if min_severity > 0:
            query += ' AND severity >= ?'
            params.append(min_severity)
        query += ' ORDER BY timestamp DESC LIMIT ?'
        params.append(limit)
        df = pd.read_sql_query(query, conn, params=params)
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
        return df

    # ─── Statistics ───────────────────────────────────────────────────────────

    def get_portfolio_stats(self) -> dict:
        """Portfolio-level statistics."""
        conn = self._get_conn()

        # Latest equity
        cur = conn.execute(
            'SELECT equity, hedge_ratio, price FROM equity_snapshots ORDER BY timestamp DESC LIMIT 1'
        )
        row = cur.fetchone()
        latest = dict(row) if row else {}

        # Peak equity
        cur = conn.execute('SELECT MAX(equity) as peak FROM equity_snapshots')
        peak = cur.fetchone()['peak'] or 0

        # Current drawdown
        current = latest.get('equity', 0)
        drawdown = (current - peak) / peak if peak else 0

        # Event stats
        cur = conn.execute('''
            SELECT event_type, COUNT(*) as cnt, MAX(severity) as max_sev
            FROM events GROUP BY event_type
        ''')
        event_stats = {r['event_type']: {'count': r['cnt'], 'max_sev': r['max_sev']}
                       for r in cur.fetchall()}

        # Signal stats
        cur = conn.execute('''
            SELECT AVG(target_ratio) as avg_ratio, MIN(target_ratio) as min_ratio,
                   MAX(target_ratio) as max_ratio
            FROM hedge_signals
        ''')
        sig = cur.fetchone()

        return {
            'latest_equity': current,
            'peak_equity': peak,
            'current_drawdown': drawdown,
            'latest_price': latest.get('price', 0),
            'latest_hedge_ratio': latest.get('hedge_ratio', 0),
            'avg_signal_ratio': sig['avg_ratio'] or 0.65,
            'min_signal_ratio': sig['min_ratio'] or 0.65,
            'max_signal_ratio': sig['max_ratio'] or 0.65,
            'event_stats': event_stats,
        }

    def get_monthly_report(self, year: int, month: int) -> dict:
        """Monthly performance report."""
        start = f'{year}-{month:02d}-01'
        end = f'{year}-{month:02d}-31'

        conn = self._get_conn()

        # Start equity
        cur = conn.execute('''
            SELECT equity FROM equity_snapshots
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp LIMIT 1
        ''', (start, end))
        row = cur.fetchone()
        start_eq = row['equity'] if row else 0

        # End equity
        cur = conn.execute('''
            SELECT equity FROM equity_snapshots
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp DESC LIMIT 1
        ''', (start, end))
        row = cur.fetchone()
        end_eq = row['equity'] if row else start_eq

        # Trade stats
        cur = conn.execute('''
            SELECT COUNT(*) as n, SUM(pnl) as pnl
            FROM hedge_trades
            WHERE entry_time >= ? AND entry_time <= ?
        ''', (start, end))
        trades = cur.fetchone()

        # Event stats
        cur = conn.execute('''
            SELECT COUNT(*) as n, MAX(severity) as max_sev
            FROM events
            WHERE timestamp >= ? AND timestamp <= ?
        ''', (start, end))
        events = cur.fetchone()

        return {
            'start_equity': start_eq,
            'end_equity': end_eq,
            'pnl': end_eq - start_eq,
            'trade_count': trades['n'] or 0,
            'trade_pnl': trades['pnl'] or 0,
            'event_count': events['n'] or 0,
            'max_severity': events['max_sev'] or 0,
        }

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
