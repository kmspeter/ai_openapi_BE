from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from config import settings
from database import async_session_factory, init_db
from models.schemas import HealthStatus
from routers import chat, usage

app = FastAPI(
    title="AI Multi-Provider Gateway",
    description="Unified API gateway for OpenAI, Anthropic, and Google Gemini models.",
    version="0.1.0",
    debug=settings.debug,
)

if settings.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(chat.router, prefix="/api")
app.include_router(usage.router, prefix="/api")


@app.on_event("startup")
async def on_startup() -> None:
    await init_db()


@app.get("/health", response_model=HealthStatus)
async def health_check() -> HealthStatus:
    database_ok = False
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        database_ok = True
    except Exception as exc:  # pragma: no cover - runtime check
        raise HTTPException(status_code=500, detail=f"Database health check failed: {exc}") from exc

    provider_status = {key: bool(value) for key, value in settings.provider_keys.items()}
    return HealthStatus(database=database_ok, providers=provider_status)


if __name__ == "__main__":
    import atexit
    from typing import Optional

    import uvicorn

    tunnel_url: Optional[str] = None

    if settings.enable_ngrok:
        from pyngrok import conf, ngrok

        if settings.ngrok_authtoken:
            ngrok.set_auth_token(settings.ngrok_authtoken)

        if settings.ngrok_region:
            conf.get_default().region = settings.ngrok_region

        tunnel = ngrok.connect(settings.port, bind_tls=True)
        tunnel_url = tunnel.public_url
        print(
            f" * ngrok tunnel available at {tunnel_url} -> http://127.0.0.1:{settings.port}",
            flush=True,
        )

        def _stop_ngrok() -> None:
            if tunnel_url:
                ngrok.disconnect(tunnel_url)
            ngrok.kill()

        atexit.register(_stop_ngrok)

    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=settings.debug)