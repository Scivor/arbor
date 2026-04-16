"""
core/persistence/__init__.py
SQLite persistence for decisions, trades, equity, events, and signals.
"""

from core.persistence.database import DecisionDB

__all__ = ['DecisionDB']
