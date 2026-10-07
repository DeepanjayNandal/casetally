"""Error masking: the client gets a reference, the log keeps the cause.

Every failure this API reports to a browser used to carry the exception text with
it. The chat stream sent a `detail` field holding `str(exc)`, and /health/ready
interpolated the exception straight into its 503 body. The UI never displayed
either, but both crossed the wire, so the driver name, the Postgres host and port,
and fragments of SQL were all readable in DevTools on a public endpoint.

The fix is the usual split. The client is told what happened in words it can act
on, plus a short reference. The reference is logged next to the full traceback, so
a user can quote eight characters and an operator can find the exact failure.

Keep ids short on purpose. These are for correlating one report against a few
hours of logs, not for uniqueness across a fleet, and a user has to be able to
read one out loud or paste it into a message.
"""

import logging
import uuid
from typing import Any

# Enough to pick one failure out of a day of logs, short enough to quote.
ERROR_ID_CHARS = 8


def new_error_id() -> str:
    """A short correlation id for one failure."""
    return uuid.uuid4().hex[:ERROR_ID_CHARS]


def report(
    logger: logging.Logger,
    summary: str,
    *args: Any,
    exc_info: bool = True,
    level: int = logging.ERROR,
) -> str:
    """Log a failure with a fresh id and return that id for the client.

    `exc_info` defaults to True because the usual caller is inside an `except`
    block and the traceback is the point. Pass False where the failure is known
    without an exception, for example a model that returned nothing, since
    logging a traceback there would record this function's own stack and imply a
    crash that did not happen.

    `level` exists for the one path that is reported to the client but is not a
    fault: a question that legitimately matched no statute. That still gets an id
    so it can be traced, but logging it at ERROR would bury real faults.
    """
    error_id = new_error_id()
    logger.log(level, "[%s] " + summary, error_id, *args, exc_info=exc_info)
    return error_id


def client_error(message: str, error_id: str) -> dict:
    """The only shape an error leaves this service in.

    No exception type, no exception text, no SQL, no host, no path. A caller that
    wants to add a field has to come through here, which is what stops a detail
    field reappearing by accident.
    """
    return {"message": message, "error_id": error_id}
