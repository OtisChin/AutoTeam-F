from __future__ import annotations

import logging

from autotoken import install_no_traceback_filter


def test_no_traceback_filter_keeps_exception_summary_without_stack():
    logger = logging.getLogger("tests.no_traceback_filter")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = install_no_traceback_filter(Capture())
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.handlers = [handler]

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logger.exception("backend failed: %s", "oauth")

    assert len(records) == 1
    rendered = handler.format(records[0])
    assert "backend failed: oauth" in rendered
    assert "RuntimeError: boom" in rendered
    assert "Traceback" not in rendered
    assert records[0].exc_info is None
