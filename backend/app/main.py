"""FastAPI application entrypoint (Section 3: one backend, three frontends).

Section 3 argues explicitly against splitting this into microservices at pilot
scale. The concession that keeps a later split cheap is that scope is enforced
by role-checked dependencies and database policies rather than by anything
service-shaped, so pulling a router out later is a refactor rather than a
rewrite.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import auth_dev, beneficiaries, captures, growth, health, reference
from app.config import get_settings
from app.db.session import dispose_engine

logger = logging.getLogger("poshannetra")

# Bilingual titles for the error codes a field worker can actually hit. The
# Hindi string travels with the response so an offline Hindi-first client needs
# no local lookup table (Section 9.1).
_TITLES: dict[int, tuple[str, str]] = {
    400: ("Bad request", "अनुचित अनुरोध"),
    401: ("Sign in required", "साइन इन आवश्यक है"),
    403: ("Not permitted", "अनुमति नहीं है"),
    404: ("Not found", "नहीं मिला"),
    415: ("Unsupported file type", "यह फ़ाइल प्रकार समर्थित नहीं है"),
    422: ("Could not process the details provided", "दी गई जानकारी संसाधित नहीं हो सकी"),
    500: ("Something went wrong", "कुछ गड़बड़ हो गई"),
    502: ("Upstream service failed", "बाहरी सेवा विफल रही"),
    503: ("Service unavailable", "सेवा उपलब्ध नहीं है"),
}


def _problem(
    status_code: int,
    code: str,
    detail: str | None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    en, hi = _TITLES.get(status_code, _TITLES[500])
    return JSONResponse(
        status_code=status_code,
        content={
            "type": "about:blank",
            "title_en": en,
            "title_hi": hi,
            "status": status_code,
            "code": code,
            "detail": detail,
        },
        media_type="application/problem+json",
        # Headers set on the HTTPException must survive. RFC 7235 requires a 401
        # to carry WWW-Authenticate, and a client that never sees it cannot tell
        # "sign in" from "you are signed in but not allowed".
        headers=headers,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    from app.ai import client as ai_client

    ai_client.export_provider_keys()
    logger.info(
        "PoshanNetra API starting (env=%s, phase=2, ai_provider=%s, ai_enabled=%s)",
        settings.app_env,
        settings.ai_provider,
        settings.ai_enabled,
    )
    if settings.ai_enabled and not settings.ai_configured:
        # Loud at startup rather than silent per-capture: without this, every
        # capture would simply stay 'pending' with no visible cause.
        logger.warning(
            "AI is enabled but provider %r has no API key; captures will stay "
            "pending. See docs/phase2-ai-setup.md",
            settings.ai_provider,
        )
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="PoshanNetra AI API",
        description=(
            "Phase 2: AI pipeline and evaluation harness.\n\n"
            "Two paths never touch a model. Growth classification is "
            "deterministic WHO LMS arithmetic over vendored reference tables "
            "(Section 6.4). Nutrition is a deterministic IFCT 2017 lookup "
            "through recipe and yield conversion (Section 6.3) -- the vision "
            "model estimates portions only, and is never asked for calories."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # Phases 3-5 add three separate frontends on Vercel. Origins are wide open
    # in development only; Phase 7 must pin them before anything is deployed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else [],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def _http_exc(_: Request, exc: HTTPException) -> JSONResponse:
        return _problem(exc.status_code, str(exc.detail), str(exc.detail), exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem(422, "validation_error", str(exc.errors()[:3]))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Log the detail, return none of it: an unhandled error must not leak a
        # DSN, a query or a beneficiary name into a response body.
        logger.exception("unhandled error", exc_info=exc)
        return _problem(500, "internal_error", None)

    for router in (
        health.router,
        auth_dev.router,
        reference.router,
        beneficiaries.router,
        growth.router,
        captures.router,
    ):
        app.include_router(router)

    return app


app = create_app()
