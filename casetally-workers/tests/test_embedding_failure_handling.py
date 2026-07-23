"""
Covers the embedding worker's batch-failure path.

That path only runs when the encoder raises, which does not happen in normal
operation: MiniLM encodes essentially any string, so the whole corpus embedded
without a single failure. These tests force the failure with a stub encoder so
the per-chunk isolation and the retry accounting are actually exercised rather
than merely written.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from embedding_worker import EmbeddingWorker  # noqa: E402


POISON_ID = 202


class StubEncoder:
    """Encoder that raises for one specific text and succeeds for the rest."""

    def __init__(self, poison_text: str):
        self.poison_text = poison_text
        self.calls: list[list[str]] = []

    def generate_batch(self, texts, batch_size: int = 32):
        self.calls.append(list(texts))
        if self.poison_text in texts:
            raise RuntimeError("simulated encoder failure")
        return [[0.0] * 384 for _ in texts]


class FakeSession:
    """Minimal stand-in that records statements instead of touching a database."""

    def __init__(self, log: list):
        self._log = log
        self.committed = False
        self.rolled_back = False

    def execute(self, statement, params=None):
        self._log.append((str(statement), params))

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


@pytest.fixture
def worker():
    """
    Build a worker without running __init__, which would require a live
    database and Redis connection. Only the collaborators the failure path
    touches are filled in.
    """
    w = EmbeddingWorker.__new__(EmbeddingWorker)
    w.max_retries = 3
    w.batch_size = 100
    w.statements: list = []
    w.SessionLocal = lambda: FakeSession(w.statements)
    return w


def test_one_bad_chunk_does_not_strand_the_rest_of_the_batch(worker):
    """A batch of three with one poison chunk should still embed the other two."""
    ids = [201, POISON_ID, 203]
    texts = ["alpha", "poison", "gamma"]
    worker.embedding_service = StubEncoder(poison_text="poison")

    succeeded = worker._process_individually(ids, texts)

    assert succeeded == 2, "the two healthy chunks should have been embedded"
    # Each chunk is encoded on its own, which is what isolates the failure.
    assert worker.embedding_service.calls == [["alpha"], ["poison"], ["gamma"]]


def test_retry_count_is_charged_only_to_the_chunk_that_raised(worker):
    """
    The naive version of this fix increments the whole batch, which would
    eventually discard every healthy chunk that happened to share a batch with
    a bad one. Only the failing id may be incremented.
    """
    worker.embedding_service = StubEncoder(poison_text="poison")

    worker._process_individually([201, POISON_ID, 203], ["alpha", "poison", "gamma"])

    increments = [
        params for sql, params in worker.statements
        if "retry_count = retry_count + 1" in sql
    ]
    assert len(increments) == 1, "exactly one retry_count update should be issued"
    assert increments[0] == {"ids": [POISON_ID]}, "only the failing chunk may be charged"


def test_no_retry_update_when_every_chunk_encodes(worker):
    """A clean batch must not touch retry_count at all."""
    worker.embedding_service = StubEncoder(poison_text="nothing-matches-this")

    succeeded = worker._process_individually([301, 302], ["alpha", "beta"])

    assert succeeded == 2
    assert not [sql for sql, _ in worker.statements if "retry_count" in sql]


def test_record_failures_uses_a_fresh_session(worker):
    """
    The counter has to be written outside the batch transaction. That
    transaction is already rolled back by the time this runs, so writing on it
    would be discarded silently and the chunk would retry forever.
    """
    dead = FakeSession(worker.statements)
    dead.rollback()

    worker._record_failures([POISON_ID])

    assert not dead.committed, "the rolled-back session must not be reused"
    assert worker.statements, "the increment should have been issued on a new session"
    sql, params = worker.statements[-1]
    assert "retry_count = retry_count + 1" in sql
    assert params == {"ids": [POISON_ID]}


def test_record_failures_is_a_no_op_for_an_empty_list(worker):
    """A batch that fails for a non-chunk reason must not charge anything."""
    worker._record_failures([])
    assert worker.statements == []
