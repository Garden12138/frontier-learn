import logging


def configure_logging() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("frontier").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").disabled = True
    # HTTP client logs otherwise include full user-supplied URLs and queries.
    for name in ("httpx", "httpcore", "sqlalchemy.engine", "asyncpg"):
        logging.getLogger(name).setLevel(logging.WARNING)
