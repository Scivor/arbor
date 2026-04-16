"""
agent/src/debate/memory.py
HedgeSituationMemory — BM25-based memory for coffee hedge decisions.

Adapts TradingAgents' FinancialSituationMemory for coffee hedging decisions.
Uses rank_bm25 (already a dependency of vendor/tradingagents) for offline
lexical similarity matching — no API calls, no token limits.

Usage:
    memory = HedgeSituationMemory("bull_memory")
    memory.add_situations([
        ("La Nina + drought in Minas Gerais, Q3 delivery at risk",
         "Increased hedge ratio to 85%, recommended buy call spread"),
    ])
    matches = memory.get_memories(current_situation, n_matches=2)
"""

from __future__ import annotations

import re
from typing import Any, List, Tuple

try:
    from rank_bm25 import BM25Okapi
    _BM25_AVAILABLE = True
except ImportError:
    BM25Okapi = None
    _BM25_AVAILABLE = False


class HedgeSituationMemory:
    """BM25-based memory for storing and retrieving past hedge decisions."""

    def __init__(self, name: str, config: dict | None = None):
        self.name = name
        self.documents: List[str] = []
        self.recommendations: List[str] = []
        self.bm25 = None

    def _tokenize(self, text: str) -> List[str]:
        """Lowercase + split on word boundaries."""
        return re.findall(r'\b\w+\b', text.lower())

    def _rebuild_index(self) -> None:
        if not _BM25_AVAILABLE:
            return
        if self.documents:
            tokenized = [self._tokenize(d) for d in self.documents]
            self.bm25 = BM25Okapi(tokenized)
        else:
            self.bm25 = None

    def add_situations(self, situations_and_advice: List[Tuple[str, str]]) -> None:
        """Add (situation, recommendation) pairs to memory."""
        for situation, recommendation in situations_and_advice:
            self.documents.append(situation)
            self.recommendations.append(recommendation)
        self._rebuild_index()

    def get_memories(
        self, current_situation: str, n_matches: int = 1
    ) -> List[dict]:
        """Find most similar past situations via BM25.

        Returns:
            List[dict] with keys: matched_situation, recommendation, similarity_score
        """
        if not self.documents or self.bm25 is None or not _BM25_AVAILABLE:
            return []

        tokens = self._tokenize(current_situation)
        scores = self.bm25.get_scores(tokens)
        top_idx = sorted(
            range(len(scores)), key=lambda i: scores[i], reverse=True
        )[:n_matches]

        results = []
        max_score = float(max(scores)) if scores and scores.max() > 0 else 1.0
        for idx in top_idx:
            results.append({
                "matched_situation": self.documents[idx],
                "recommendation": self.recommendations[idx],
                "similarity_score": scores[idx] / max_score,
            })
        return results

    def clear(self) -> None:
        """Wipe all stored memories."""
        self.documents = []
        self.recommendations = []
        self.bm25 = None
