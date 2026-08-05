"""Melo three-tier memory system — voice-agent native memory architecture.

  * `short_term` — sliding window of recent chat messages (in-memory).
  * `working`    — scratch state for the current task (in-memory dict).
  * `long_term`  — cross-session facts persisted to the DB + optional
                   vector index for semantic recall.

All three tiers share a uniform interface. The `LongTermStore`
abstraction decouples call sites from the storage backend — the
in-memory substring matcher, Postgres + pgvector, and standalone
vector stores all implement the same surface, selectable per
deployment.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol

from melo.llm.base import ChatMessage

logger = logging.getLogger(__name__)


@dataclass
class LongTermFact:
    """A single persisted fact / memory entry."""

    id: str
    content: str
    role: str = "user"  # who said it / who it's about
    metadata: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    score: float = 0.0  # relevance score from retrieval


class LongTermStore(Protocol):
    """Persistence backend for long-term memory.

    The `InMemoryLongTermStore` provides a substring-matching
    implementation suitable for tests and dev. Postgres + pgvector
    and other backends implement the same surface.
    """

    async def add(self, fact: LongTermFact) -> None: ...

    async def search(self, query: str, *, k: int = 5) -> list[LongTermFact]: ...

    async def delete(self, fact_id: str) -> None: ...


class InMemoryLongTermStore:
    """Process-local long-term store.

    Uses substring matching for `search` — runs the recall path in tests
    and dev without a vector DB. Coexists with persistent backends
    (Postgres + pgvector), injected via `MemorySystem(long_term=...)`.
    """

    def __init__(self) -> None:
        self._facts: dict[str, LongTermFact] = {}
        self._lock = threading.Lock()

    async def add(self, fact: LongTermFact) -> None:
        with self._lock:
            self._facts[fact.id] = fact

    async def search(self, query: str, *, k: int = 5) -> list[LongTermFact]:
        q = query.lower()
        with self._lock:
            matches = [
                f for f in self._facts.values() if q and q in f.content.lower()
            ]
        matches.sort(key=lambda f: f.created_at, reverse=True)
        return matches[:k]

    async def delete(self, fact_id: str) -> None:
        with self._lock:
            self._facts.pop(fact_id, None)

    async def clear(self) -> None:
        with self._lock:
            self._facts.clear()


class WorkingMemory:
    """Scratch state for the current task.

    Free-form key/value bag plus an ordered list of pending steps.
    Used by the planner to track progress mid-task; cleared between
    unrelated turns.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._steps: list[str] = []
        self._done: list[str] = []

    # key/value storage
    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def pop(self, key: str, default: Any = None) -> Any:
        return self._data.pop(key, default)

    # step queue
    def set_steps(self, steps: list[str]) -> None:
        self._steps = list(steps)
        self._done.clear()

    def next_step(self) -> str | None:
        if not self._steps:
            return None
        step = self._steps.pop(0)
        self._done.append(step)
        return step

    def remaining(self) -> list[str]:
        return list(self._steps)

    def completed(self) -> list[str]:
        return list(self._done)

    def clear(self) -> None:
        self._data.clear()
        self._steps.clear()
        self._done.clear()

    @property
    def is_active(self) -> bool:
        return bool(self._steps) or bool(self._data)


class MemorySystem:
    """Three-tier memory orchestrator.

    Tiers:
      * `short_term` — `deque[ChatMessage]`, capped at `short_term_limit`.
      * `working`    — `WorkingMemory` instance.
      * `long_term`  — pluggable `LongTermStore`.
    """

    def __init__(
        self,
        *,
        short_term_limit: int = 32,
        long_term: LongTermStore | None = None,
    ) -> None:
        self.short_term_limit = short_term_limit
        self._short_term: deque[ChatMessage] = deque(maxlen=short_term_limit)
        self.working = WorkingMemory()
        self.long_term: LongTermStore = long_term or InMemoryLongTermStore()

    # -- short-term --------------------------------------------------------

    def add_message(self, msg: ChatMessage) -> None:
        self._short_term.append(msg)

    def add_turn(self, user: str, assistant: str) -> None:
        self._short_term.append(ChatMessage(role="user", content=user))
        self._short_term.append(ChatMessage(role="assistant", content=assistant))

    @property
    def short_term(self) -> list[ChatMessage]:
        return list(self._short_term)

    def clear_short_term(self) -> None:
        self._short_term.clear()

    # -- long-term --------------------------------------------------------

    async def remember(self, content: str, *, role: str = "user", metadata: dict | None = None) -> LongTermFact:
        import uuid

        fact = LongTermFact(
            id=str(uuid.uuid4()),
            content=content,
            role=role,
            metadata=metadata or {},
        )
        await self.long_term.add(fact)
        return fact

    async def recall(self, query: str, *, k: int = 5) -> list[LongTermFact]:
        return await self.long_term.search(query, k=k)

    async def forget(self, fact_id: str) -> None:
        await self.long_term.delete(fact_id)

    # -- snapshot ----------------------------------------------------------

    def to_messages(self, *, system: str | None = None) -> list[ChatMessage]:
        """Render the memory as a chat-message list for LLM calls.

        Order: [system?] + short_term + (caller is expected to append
        the new user message). Long-term facts are surfaced
        out-of-band via `recall()` — they're not auto-injected here
        because retrieval is query-dependent.
        """
        msgs: list[ChatMessage] = []
        if system:
            msgs.append(ChatMessage(role="system", content=system))
        msgs.extend(self._short_term)
        return msgs

    def reset(self) -> None:
        """Clear short-term + working memory; long-term is preserved."""
        self._short_term.clear()
        self.working.clear()
