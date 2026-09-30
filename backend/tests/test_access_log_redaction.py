import logging

import pytest

from app.core.http_auth import APIWriteAuthMiddleware


@pytest.mark.parametrize("key", ["token", "api_key", "apiKey", "super_api_key", "superApiKey", "%74oken"])
def test_access_logs_redact_query_credentials_and_preserve_other_fields(caplog, key):
    # Use Uvicorn's actual access logger and argument layout, including duplicates.
    APIWriteAuthMiddleware(lambda scope, receive, send: None)
    logger = logging.getLogger("uvicorn.access")
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:4321", "GET",
                    f"/api/analysis/runs/RUN_TEST/stream?{key}=synthetic-secret&after=12&{key}=second-secret", "1.1", 200)
    assert "synthetic-secret" not in caplog.text
    assert "second-secret" not in caplog.text
    assert "after=12" in caplog.text
    assert "RUN_TEST/stream" in caplog.text
    assert "200" in caplog.text


def test_access_log_filter_preserves_non_query_and_non_access_messages(caplog):
    APIWriteAuthMiddleware(lambda scope, receive, send: None)
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logger = logging.getLogger("uvicorn.access")
        logger.info('%s - "%s %s HTTP/%s" %d', "local", "GET", "/api/health?mode=read", "1.1", 200)
        logger.info("server diagnostic %s", "kept")
    assert "/api/health?mode=read" in caplog.text
    assert "server diagnostic kept" in caplog.text
