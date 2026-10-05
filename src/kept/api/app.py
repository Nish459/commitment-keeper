import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from kept import __version__
from kept.adapters.llm import LLMError
from kept.api.routes import router
from kept.config import get_settings
from kept.container import Container, build_container
from kept.domain.errors import SearchError
from kept.services.keeper import CommitmentNotFoundError, NotPreparableError
from kept.services.review import DraftAlreadyReviewedError, DraftNotFoundError

logger = logging.getLogger("kept")

_STATUS_BY_ERROR: dict[type[Exception], int] = {
    CommitmentNotFoundError: 404,
    DraftNotFoundError: 404,
    NotPreparableError: 409,
    DraftAlreadyReviewedError: 409,
    SearchError: 502,
    LLMError: 502,
}


def create_app(container: Container | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = container is None
        app.state.container = container or build_container(get_settings())
        try:
            yield
        finally:
            if owned:
                await app.state.container.aclose()

    app = FastAPI(title="Kept", version=__version__, lifespan=lifespan)
    if container is not None:
        app.state.container = container
    app.include_router(router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    def _handle(_: Request, exc: Exception) -> JSONResponse:
        status = next(code for t, code in _STATUS_BY_ERROR.items() if isinstance(exc, t))
        if status >= 500:
            logger.warning("upstream failure: %s", exc)
        return JSONResponse({"detail": str(exc)}, status_code=status)

    for error_type in _STATUS_BY_ERROR:
        app.add_exception_handler(error_type, _handle)
    return app
