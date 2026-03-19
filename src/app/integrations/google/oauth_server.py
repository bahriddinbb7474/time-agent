from __future__ import annotations

import asyncio
import logging
import warnings
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from aiohttp import web

from app.integrations.google.auth import build_flow, save_credentials

logger = logging.getLogger("time-agent.gcal")


@dataclass(frozen=True)
class OAuthServerConfig:
    bind_host: str
    port: int
    timeout_sec: int = 300


class OAuthCallbackServer:
    def __init__(
        self,
        config: OAuthServerConfig,
        consume_state_fn: Callable[[str], Awaitable[tuple[int, str] | None]],
        on_success_fn: Callable[[int], Awaitable[None]],
    ):
        self._config = config
        self._consume_state_fn = consume_state_fn
        self._on_success_fn = on_success_fn

        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._task: Optional[asyncio.Task] = None

        self._done_event = asyncio.Event()
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def start_once(self) -> None:
        if self._is_running:
            return

        app = web.Application()
        app.router.add_get("/oauth2callback", self._handle_callback)

        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()

        self._site = web.TCPSite(
            self._runner,
            host=self._config.bind_host,
            port=self._config.port,
        )
        await self._site.start()

        self._is_running = True
        logger.info(
            "OAuth callback server started on %s:%s",
            self._config.bind_host,
            self._config.port,
        )

        self._task = asyncio.create_task(self._run_until_done())

    async def _run_until_done(self) -> None:
        try:
            await asyncio.wait_for(
                self._done_event.wait(),
                timeout=self._config.timeout_sec,
            )
        except asyncio.TimeoutError:
            logger.info("OAuth callback server timeout; stopping.")
        except Exception:
            logger.exception("OAuth callback server loop error; stopping.")
        finally:
            await self.stop()

    async def stop(self) -> None:
        if not self._is_running:
            return

        self._is_running = False

        try:
            if self._site:
                await self._site.stop()
            if self._runner:
                await self._runner.cleanup()
        finally:
            self._site = None
            self._runner = None

        logger.info("OAuth callback server stopped.")

    async def _handle_callback(self, request: web.Request) -> web.Response:
        error = request.query.get("error")
        if error:
            return web.Response(
                text="Authorization failed (Google error). You can close this tab.",
                status=400,
            )

        code = request.query.get("code")
        state = request.query.get("state")

        if not code or not state:
            return web.Response(
                text="Missing parameters. You can close this tab.",
                status=400,
            )

        consumed = await self._consume_state_fn(state)
        if consumed is None:
            return web.Response(
                text="State invalid or expired. You can close this tab.",
                status=401,
            )

        user_id, code_verifier = consumed

        try:
            flow = build_flow(state=state)
            flow.code_verifier = code_verifier

            # Google может вернуть расширенный набор scopes
            # (например ранее выданный readonly + новый events).
            # oauthlib иногда поднимает это как Warning, что ломает callback.
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r"Scope has changed.*",
                    category=Warning,
                )
                flow.fetch_token(code=code)

            creds = flow.credentials
            save_credentials(creds)

        except Exception:
            logger.exception("OAuth token exchange failed (details hidden).")
            return web.Response(
                text="Authorization failed. You can close this tab.",
                status=500,
            )

        try:
            await self._on_success_fn(int(user_id))
        except Exception:
            logger.exception("OAuth on_success hook failed.")

        self._done_event.set()

        html = (
            "<html><body><h3>Authorized ✅</h3>"
            "<p>You can close this tab.</p></body></html>"
        )
        return web.Response(text=html, content_type="text/html")
