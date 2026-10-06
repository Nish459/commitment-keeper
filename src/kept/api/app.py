import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from kept import __version__
from kept.adapters.llm import LLMError
from kept.api.routes import router
from kept.config import Settings, get_settings
from kept.container import Container, build_container
from kept.demo import COOKIE_NAME, SessionManager, build_session_manager
from kept.domain.errors import (
    AccessDeniedError,
    DemoLimitError,
    EmailError,
    EmailNotConfiguredError,
    NoDueDateError,
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
    AccessDeniedError: 403,
    DemoLimitError: 429,
    EmailNotConfiguredError: 409,
    NoDueDateError: 409,
    RecipientNotAllowedError: 403,
    EmailError: 502,
    LLMError: 502,
}


def create_app(
    container: Container | None = None,
    *,
    sessions: SessionManager | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    config = settings or (container.settings if container else get_settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        owned_sessions = sessions
        owned_container = container
        if container is None and sessions is None:
            if config.demo_mode:
                owned_sessions = build_session_manager(config)
            else:
                owned_container = build_container(config)
        app.state.sessions = owned_sessions
        app.state.container = owned_container
        logger.info(
            "models nano=%s super=%s ultra=%s%s",
            config.model_nano,
            config.model_super,
            config.model_ultra,
            " (demo mode: isolated workspaces, email off)" if config.demo_mode else "",
        )
        try:
            yield
        finally:
            if container is None and sessions is None:
                if owned_sessions:
                    await owned_sessions.aclose()
                if owned_container:
                    await owned_container.aclose()

    app = FastAPI(title="Kept", version=__version__, lifespan=lifespan)
    # Set eagerly so apps used without running the lifespan (tests) still work.
    app.state.container = container
    app.state.sessions = sessions
    app.include_router(router)

    @app.middleware("http")
    async def demo_workspace(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """In demo mode, give each visitor their own workspace and keep it via a cookie.

        Done here rather than in a dependency so the cookie is set on error responses too,
        and so static files never create workspaces.
        """
        manager: SessionManager | None = app.state.sessions
        if manager is None or not request.url.path.startswith("/api/"):
            return await call_next(request)
        await manager.reap()
        try:
            session_id, workspace, _ = manager.get_or_create(
                request.cookies.get(COOKIE_NAME),
                client=request.client.host if request.client else "",
            )
        except DemoLimitError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=429)
        request.state.workspace = workspace
        response = await call_next(request)
        response.set_cookie(
            COOKIE_NAME,
            session_id,
            max_age=workspace.settings.demo_session_minutes * 60,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            path="/",
        )
        return response

    @app.get("/health")
    def health() -> dict[str, object]:
        """Liveness plus which credentials are configured (never their values)."""
        return {
            "status": "ok",
            "version": __version__,
            "nebius_key_set": bool(config.nebius_api_key.get_secret_value()),
            "tavily_key_set": bool(config.tavily_api_key.get_secret_value()),
        }

    def _handle(_: Request, exc: Exception) -> JSONResponse:
        status = next(code for t, code in _STATUS_BY_ERROR.items() if isinstance(exc, t))
        if status >= 500:
            logger.warning("upstream failure: %s", exc)
        return JSONResponse({"detail": str(exc)}, status_code=status)

    for error_type in _STATUS_BY_ERROR:
        app.add_exception_handler(error_type, _handle)

    if config.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=config.web_dir, html=True), name="web")
    return app
