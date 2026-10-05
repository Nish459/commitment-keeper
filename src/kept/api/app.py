import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from kept import __version__
from kept.adapters.llm import LLMError
from kept.api.routes import router
from kept.config import get_settings
from kept.container import Container, build_container
from kept.domain.errors import (
    EmailError,
    EmailNotConfiguredError,
    RecipientNotAllowedError,
    SearchError,
)
from kept.services.keeper import CommitmentNotFoundError, NotPreparableError, UngroundedDraftError
from kept.services.review import DraftAlreadyReviewedError, DraftNotFoundError

logger = logging.getLogger("kept")

_STATUS_BY_ERROR: dict[type[Exception], int] = {
    CommitmentNotFoundError: 404,
    DraftNotFoundError: 404,
    NotPreparableError: 409,
    DraftAlreadyReviewedError: 409,
    SearchError: 502,
    UngroundedDraftError: 502,
    EmailNotConfiguredError: 409,
    RecipientNotAllowedError: 403,
    EmailError: 502,
    LLMError: 502,
}


def create_app(container: Container | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = container is None
        if owned:
            logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        app.state.container = container or build_container(get_settings())
        settings = app.state.container.settings
        logger.info(
            "models nano=%s super=%s ultra=%s",
            settings.model_nano,
            settings.model_super,
            settings.model_ultra,
        )
        try:
            yield
        finally:
            if owned:
                await app.state.container.aclose()

    app = FastAPI(title="Kept", version=__version__, lifespan=lifespan)
    if container is not None:
        app.state.container = container
    app.include_router(router)

    @app.get("/health")
    def health(request: Request) -> dict[str, object]:
        """Liveness plus which credentials are configured (never their values)."""
        settings = request.app.state.container.settings
        return {
            "status": "ok",
            "version": __version__,
            "nebius_key_set": bool(settings.nebius_api_key.get_secret_value()),
            "tavily_key_set": bool(settings.tavily_api_key.get_secret_value()),
        }

    def _handle(_: Request, exc: Exception) -> JSONResponse:
        status = next(code for t, code in _STATUS_BY_ERROR.items() if isinstance(exc, t))
        if status >= 500:
            logger.warning("upstream failure: %s", exc)
        return JSONResponse({"detail": str(exc)}, status_code=status)

    for error_type in _STATUS_BY_ERROR:
        app.add_exception_handler(error_type, _handle)

    web_dir = (container.settings if container else get_settings()).web_dir
    if web_dir.is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app
