"""Covers the error-masking contract: references out, exception text stays in.

Every failure this service reports used to carry the exception with it. The chat
stream sent a `detail` field holding `str(exc)` and /health/ready interpolated the
exception into its 503 body, so a failed query published the driver name, the
Postgres host and the port to anyone with DevTools open.

These tests assert the two halves of the fix together, because either one alone
is useless. The client payload must contain no internal text and must carry an
id, and the log must contain the real exception under that same id. Checking only
the payload would pass against a service that masked errors and then forgot them.

The sentinel below is deliberately shaped like the thing that leaked: a driver
name, a host and a port. If any of it reaches a client payload, the test fails.
"""

import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

import app.api.search as search_api  # noqa: E402
import app.main as main_module  # noqa: E402
import app.routers.chat as chat_module  # noqa: E402
from app.errors import ERROR_ID_CHARS, client_error, new_error_id, report  # noqa: E402

# Everything an attacker would want out of an error, in one string.
SECRET = "OperationalError: could not connect to server: casetally-postgres:5432 dbname=casetally_law"

# Fragments checked individually, so a partial leak cannot slip through a test
# that only looks for the whole sentence.
LEAK_FRAGMENTS = [
    "OperationalError",
    "casetally-postgres",
    "5432",
    "casetally_law",
    "could not connect",
    "Traceback",
    "/app/",
    "SELECT",
]


def assert_clean(payload: dict, where: str) -> str:
    """No internal text anywhere in the payload, and an id that looks right."""
    blob = json.dumps(payload)
    for fragment in LEAK_FRAGMENTS:
        assert fragment not in blob, f"{where} leaked {fragment!r}: {blob}"
    assert "detail" not in payload, f"{where} still sends a detail field: {blob}"
    error_id = payload.get("error_id")
    assert error_id, f"{where} has no error_id: {blob}"
    assert len(error_id) == ERROR_ID_CHARS, f"{where} id is {error_id!r}"
    assert all(c in "0123456789abcdef" for c in error_id), f"{where} id is {error_id!r}"
    return error_id


# ---------------------------------------------------------------------------
# the helper itself
# ---------------------------------------------------------------------------


def test_error_id_is_short_hex_and_unique():
    ids = {new_error_id() for _ in range(200)}
    assert len(ids) == 200, "ids collided"
    for value in ids:
        assert len(value) == ERROR_ID_CHARS
        assert all(c in "0123456789abcdef" for c in value)


def test_client_error_shape_has_no_room_for_a_detail():
    body = client_error("friendly", "abcd1234")
    assert body == {"message": "friendly", "error_id": "abcd1234"}


def test_report_logs_the_exception_under_the_returned_id(caplog):
    logger = logging.getLogger("test.report")
    with caplog.at_level(logging.ERROR):
        try:
            raise RuntimeError(SECRET)
        except RuntimeError:
            error_id = report(logger, "retrieval failed for %r", "can my boss fire me")

    record = next(r for r in caplog.records if error_id in r.getMessage())
    assert "retrieval failed" in record.getMessage()
    # The traceback and the exception text must be in the log, not in the client.
    assert record.exc_info is not None
    assert SECRET in logging.Formatter().format(record)


def test_report_without_exc_info_records_no_traceback(caplog):
    logger = logging.getLogger("test.report.noexc")
    with caplog.at_level(logging.ERROR):
        error_id = report(logger, "empty answer for %r", "q", exc_info=False)
    record = next(r for r in caplog.records if error_id in r.getMessage())
    # logging passes exc_info straight through, so this is False rather than
    # None. Either way no traceback is attached, which is what matters: the
    # formatter only appends one when exc_info is truthy.
    assert not record.exc_info
    assert "Traceback" not in logging.Formatter().format(record)


# ---------------------------------------------------------------------------
# the SSE error event
# ---------------------------------------------------------------------------


def test_error_event_carries_an_id_and_no_detail():
    raw = chat_module._error_event("Search is temporarily unavailable.", "a1b2c3d4")
    assert raw.startswith("data: ")
    payload = json.loads(raw[len("data: "):].strip())
    assert payload["type"] == "error"
    assert payload["message"] == "Search is temporarily unavailable."
    assert_clean(payload, "_error_event")


def test_error_event_cannot_be_called_without_an_id():
    """The old signature defaulted detail to "". This one has no optional slot."""
    with pytest.raises(TypeError):
        chat_module._error_event("message only")


# ---------------------------------------------------------------------------
# the HTTP surfaces
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """TestClient without the lifespan, so no embedding model is loaded."""
    return TestClient(main_module.app)


def test_health_ready_masks_the_database_error(client, monkeypatch, caplog):
    def exploding_session():
        raise RuntimeError(SECRET)

    monkeypatch.setattr(main_module, "SessionLocal", exploding_session)

    with caplog.at_level(logging.ERROR):
        response = client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unavailable"
    error_id = assert_clean(payload, "/health/ready")

    logged = "\n".join(logging.Formatter().format(r) for r in caplog.records)
    assert error_id in logged, "id is not traceable in the log"
    assert SECRET in logged, "the real cause did not reach the log"


def test_health_live_stays_static(client):
    """Liveness must not touch the database, so it has nothing to leak."""
    assert client.get("/health/live").json() == {"status": "ok"}


def test_search_masks_a_retrieval_failure(client, monkeypatch, caplog):
    def exploding_search(**kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(search_api.search_service, "search", exploding_search)
    monkeypatch.setattr(search_api, "get_db", lambda: iter([None]))
    main_module.app.dependency_overrides[search_api.get_db] = lambda: None

    try:
        with caplog.at_level(logging.ERROR):
            response = client.post("/v1/search", json={"query": "age discrimination"})
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 503
    error_id = assert_clean(response.json(), "/v1/search")

    logged = "\n".join(logging.Formatter().format(r) for r in caplog.records)
    assert error_id in logged
    assert SECRET in logged


def test_search_weight_validation_still_speaks_plainly(client):
    """A deliberate 400 is not masked: its message was written for the user."""
    main_module.app.dependency_overrides[search_api.get_db] = lambda: None
    try:
        response = client.post(
            "/v1/search",
            # min_length=2 on query, so a 1-char probe would 422 on validation
            # and never reach the weight check this test is about.
            json={"query": "age", "weight_bm25": 0, "weight_vector": 0},
        )
    finally:
        main_module.app.dependency_overrides.clear()
    assert response.status_code == 400
    assert "weight" in json.dumps(response.json()).lower()


def test_unhandled_exception_handler_masks_and_correlates(caplog):
    @main_module.app.get("/__boom__")
    def boom():
        raise RuntimeError(SECRET)

    # raise_server_exceptions=False so the handler runs instead of the
    # exception propagating into the test.
    local = TestClient(main_module.app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR):
        response = local.get("/__boom__")

    assert response.status_code == 500
    error_id = assert_clean(response.json(), "global handler")

    logged = "\n".join(logging.Formatter().format(r) for r in caplog.records)
    assert error_id in logged
    assert SECRET in logged


def test_no_route_returns_an_exception_string():
    """Sweep: nothing in the app's error surface echoes our sentinel.

    raise_server_exceptions=False so an unhandled error goes through the global
    handler, which is the thing being tested. The artifact probe is included
    precisely because a None session makes it raise, and the response still has
    to come back masked.
    """
    sweep = TestClient(main_module.app, raise_server_exceptions=False)
    main_module.app.dependency_overrides[search_api.get_db] = lambda: None
    try:
        probes = [
            sweep.get("/health/live"),
            sweep.get("/health/ready"),
            sweep.post("/v1/search", json={"query": "age", "weight_bm25": 0, "weight_vector": 0}),
            sweep.post("/v1/rewrite", json={"query": "age"}),
            sweep.get("/v1/artifacts/999999999/file"),
        ]
    finally:
        main_module.app.dependency_overrides.clear()

    for response in probes:
        blob = response.text
        for fragment in ("OperationalError", "Traceback", "psycopg2", "sqlalchemy"):
            assert fragment not in blob, f"{response.request.url} leaked {fragment}"
