"""Remove accepted query credentials from Uvicorn access log records."""
import logging
from urllib.parse import unquote_plus


_CREDENTIAL_QUERY_KEYS = {"token", "api_key", "apikey", "super_api_key", "superapikey"}


class QueryCredentialFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn h11/httptools use (client, method, path, version, status).
        if not isinstance(record.args, tuple) or len(record.args) != 5 or not isinstance(record.args[2], str):
            return True
        path, separator, query = record.args[2].partition("?")
        if not separator:
            return True
        fields = []
        for field in query.split("&"):
            key, equals, value = field.partition("=")
            if unquote_plus(key).lower() in _CREDENTIAL_QUERY_KEYS:
                field = key + "=<redacted>"
            fields.append(field)
        args = list(record.args)
        args[2] = path + "?" + "&".join(fields)
        record.args = tuple(args)
        return True


def install_access_log_redaction() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, QueryCredentialFilter) for item in logger.filters):
        logger.addFilter(QueryCredentialFilter())
