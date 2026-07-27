"""A first-class Hermes Gateway platform for the local Ameath desktop pet."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import secrets
import tempfile
import uuid
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult
from gateway.session import SessionSource


PLATFORM_NAME = "ameath_desktop"
CHAT_ID = "desktop"
RUNTIME_FILENAME = "ameath_desktop_runtime.json"


class AmeathDesktopAdapter(BasePlatformAdapter):
    """Hermes-owned local WebSocket transport for the PySide desktop client."""

    def __init__(self, config: PlatformConfig) -> None:
        super().__init__(config, Platform(PLATFORM_NAME))
        self._clients: set[web.WebSocketResponse] = set()
        self._runner: web.AppRunner | None = None
        self._token = ""
        self._port: int | None = None

    @property
    def authorization_is_upstream(self) -> bool:
        # Every inbound message is accepted only after a fresh, loopback-only
        # token handshake controlled by this adapter. There is no remote user.
        return True

    def supports_draft_streaming(self, chat_type: str | None = None, metadata: dict | None = None) -> bool:
        return True

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        del is_reconnect
        if self._runner is not None:
            return True
        self._token = secrets.token_urlsafe(32)
        app = web.Application()
        app.router.add_get("/health", self._health)
        app.router.add_get("/ameath-desktop", self._websocket)
        runner = web.AppRunner(app)
        await runner.setup()
        requested_port = int((getattr(self.config, "extra", {}) or {}).get("port", 0) or 0)
        site = web.TCPSite(runner, "127.0.0.1", requested_port)
        await site.start()
        sockets = getattr(getattr(site, "_server", None), "sockets", [])
        if not sockets:
            await runner.cleanup()
            return False
        self._port = int(sockets[0].getsockname()[1])
        self._runner = runner
        self._running = True
        self._write_runtime("ready")
        return True

    async def disconnect(self) -> None:
        self._write_runtime("stopping")
        for socket in list(self._clients):
            await socket.close(code=1001, message=b"Hermes gateway stopping")
        self._clients.clear()
        if self._runner is not None:
            await self._runner.cleanup()
        self._runner = None
        self._running = False
        try:
            self._runtime_path.unlink(missing_ok=True)
        except OSError:
            pass

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        del reply_to, metadata
        if chat_id != CHAT_ID:
            return SendResult(success=False, error="Unknown Ameath desktop chat")
        await self._broadcast({"type": "message", "content": content, "final": True})
        return SendResult(success=True, message_id=uuid.uuid4().hex)

    async def send_draft(
        self,
        chat_id: str,
        draft_id: int,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        del metadata
        if chat_id != CHAT_ID:
            return SendResult(success=False, error="Unknown Ameath desktop chat")
        await self._broadcast({"type": "draft", "draft_id": draft_id, "content": content})
        return SendResult(success=True)

    async def send_typing(self, chat_id: str, metadata: dict | None = None) -> None:
        del metadata
        if chat_id == CHAT_ID:
            await self._broadcast({"type": "status", "state": "thinking", "content": "Hermes 正在处理…"})

    async def stop_typing(self, chat_id: str) -> None:
        if chat_id == CHAT_ID:
            await self._broadcast({"type": "status", "state": "idle", "content": ""})

    async def send_clarify(
        self,
        chat_id: str,
        question: str,
        choices: list | None,
        clarify_id: str,
        session_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        del metadata
        await self._broadcast(
            {
                "type": "clarify_request",
                "question": question,
                "choices": [str(choice) for choice in choices or []],
                "clarify_id": clarify_id,
                "session_key": session_key,
            }
        )
        return SendResult(success=True, message_id=uuid.uuid4().hex)

    async def send_exec_approval(
        self,
        chat_id: str,
        command: str,
        session_key: str,
        description: str = "dangerous command",
        metadata: dict[str, Any] | None = None,
        allow_permanent: bool = True,
        allow_session: bool = True,
        smart_denied: bool = False,
    ) -> SendResult:
        del metadata
        await self._broadcast(
            {
                "type": "approval_request",
                "question": description,
                "command": command,
                "session_key": session_key,
                "allow_permanent": allow_permanent and not smart_denied,
                "allow_session": allow_session,
            }
        )
        return SendResult(success=True, message_id=uuid.uuid4().hex)

    async def send_slash_confirm(
        self,
        chat_id: str,
        title: str,
        message: str,
        session_key: str,
        confirm_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        del chat_id, session_key, metadata
        await self._broadcast({"type": "slash_confirm", "title": title, "question": message, "confirm_id": confirm_id})
        return SendResult(success=True, message_id=uuid.uuid4().hex)

    async def get_chat_info(self, chat_id: str) -> dict[str, str]:
        return {"name": "Ameath Desktop", "type": "dm", "chat_id": chat_id}

    async def _health(self, _request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "platform": PLATFORM_NAME})

    async def _websocket(self, request: web.Request) -> web.StreamResponse:
        if not secrets.compare_digest(request.query.get("token", ""), self._token):
            return web.Response(status=401, text="unauthorized")
        socket = web.WebSocketResponse(heartbeat=20)
        await socket.prepare(request)
        self._clients.add(socket)
        await socket.send_json({"type": "ready", "platform": PLATFORM_NAME, "chat_id": CHAT_ID})
        try:
            async for message in socket:
                if message.type == WSMsgType.TEXT:
                    await self._handle_client_message(message.data)
                elif message.type == WSMsgType.ERROR:
                    break
        finally:
            self._clients.discard(socket)
        return socket

    async def _handle_client_message(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except ValueError:
            return
        if not isinstance(payload, dict):
            return
        event_type = payload.get("type")
        if event_type == "user_message":
            text = payload.get("text")
            if isinstance(text, str) and text.strip() and len(text) <= 32_000:
                event = MessageEvent(
                    text=text.strip(),
                    message_type=MessageType.TEXT,
                    source=self._source(),
                    message_id=uuid.uuid4().hex,
                    metadata={"ameath_desktop": True},
                )
                await self.handle_message(event)
        elif event_type == "approval":
            session_key, choice = payload.get("session_key"), payload.get("choice")
            if isinstance(session_key, str) and isinstance(choice, str) and choice in {"approve", "deny", "always", "session"}:
                from tools.approval import resolve_gateway_approval

                resolve_gateway_approval(session_key, choice)
        elif event_type == "clarify":
            clarify_id, response = payload.get("clarify_id"), payload.get("response")
            if isinstance(clarify_id, str) and isinstance(response, str) and response.strip():
                from tools.clarify_gateway import resolve_gateway_clarify

                resolve_gateway_clarify(clarify_id, response.strip())
        elif event_type == "slash_confirm":
            confirm_id, choice = payload.get("confirm_id"), payload.get("choice")
            resolver = getattr(self.gateway_runner, "_resolve_slash_confirm", None)
            if isinstance(confirm_id, str) and isinstance(choice, str) and callable(resolver):
                result = resolver(confirm_id, choice)
                if inspect.isawaitable(result):
                    await result

    def _source(self) -> SessionSource:
        return SessionSource(
            platform=self.platform,
            chat_id=CHAT_ID,
            chat_name="Ameath Desktop",
            chat_type="dm",
            user_id="local-desktop-owner",
            user_name="Local desktop owner",
            role_authorized=True,
        )

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        stale: list[web.WebSocketResponse] = []
        for socket in tuple(self._clients):
            if socket.closed:
                stale.append(socket)
                continue
            try:
                await socket.send_json(payload)
            except Exception:
                stale.append(socket)
        for socket in stale:
            self._clients.discard(socket)

    @property
    def _runtime_path(self) -> Path:
        return Path(os.getenv("HERMES_HOME", r"D:\hermes")) / RUNTIME_FILENAME

    def _write_runtime(self, state: str) -> None:
        if self._port is None:
            return
        payload = {"state": state, "port": self._port, "token": self._token, "pid": os.getpid()}
        path = self._runtime_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
                json.dump(payload, handle)
                temporary = Path(handle.name)
            temporary.replace(path)
        except OSError:
            pass


def check_requirements() -> bool:
    return True


def validate_config(_config: PlatformConfig) -> bool:
    return True


def register(ctx) -> None:
    ctx.register_platform(
        name=PLATFORM_NAME,
        label="Ameath Desktop",
        adapter_factory=lambda config: AmeathDesktopAdapter(config),
        check_fn=check_requirements,
        validate_config=validate_config,
        is_connected=lambda config: bool(getattr(config, "enabled", False)),
        max_message_length=32_000,
        emoji="🖥️",
        pii_safe=True,
        platform_hint=(
            "You are communicating through the user's local Ameath desktop terminal. "
            "Use concise, readable replies. Native confirmations and status are supported."
        ),
    )
