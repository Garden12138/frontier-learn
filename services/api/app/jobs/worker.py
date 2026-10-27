"""Bounded PostgreSQL job worker. Domain handlers are registered by each feature."""

import asyncio
import logging
import signal

from app.ai.openai_provider import OpenAIProvider
from app.ai.provider import LLMProvider
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.domain.conversation_learning import conversation_handler
from app.domain.knowledge_sync import sync_handler
from app.domain.tutor import tutor_handler
from app.domain.writeback import writeback_handler
from app.jobs.service import Handler, run_one
from app.persistence.database import create_database_engine, create_session_factory

logger = logging.getLogger("frontier.worker")


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    engine = create_database_engine(get_settings())
    factory = create_session_factory(engine)
    config = get_settings()
    provider: LLMProvider | None = None
    if config.llm_provider == "openai_responses" and config.openai_api_key:
        provider = OpenAIProvider(config.openai_api_key, config.openai_model)
    handlers: dict[str, Handler] = {
        "GITHUB_SYNC": sync_handler(factory, get_settings()),
        "TUTOR_GUIDE": tutor_handler(
            factory, provider, settings=config, fallback_without_consent=True
        ),
        "CONVERSATION_IMPORT": conversation_handler(factory),
        "GITHUB_WRITEBACK": writeback_handler(factory, get_settings()),
    }
    logger.info('{"event":"worker_started"}')
    try:
        while not stop.is_set():
            try:
                found = await run_one(factory, handlers)
            except Exception:
                # Never print driver exception messages or source payloads.
                logger.error('{"event":"worker_poll_failed","error_code":"DATABASE_UNAVAILABLE"}')
                found = False
            if not found:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1)
                except TimeoutError:
                    pass
    finally:
        await engine.dispose()
        logger.info('{"event":"worker_stopped"}')


if __name__ == "__main__":
    configure_logging()
    asyncio.run(main())
