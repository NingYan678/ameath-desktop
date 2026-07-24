from __future__ import annotations

import subprocess
import time
import uuid
import json
from dataclasses import dataclass

import httpx

from .butler_protocol import ButlerReply, parse_butler_reply
from .config import Settings
from .hermes_bridge import LocalHermesBridge


SYSTEM_PROMPT = """You are Aemeath, a concise and warm Chinese Windows desktop butler pet.
Never call tools, browse, access files, execute commands, or take external actions.
You may only PROPOSE one local reminder action: create_reminder, update_reminder, or cancel_reminder.
The desktop pet, not you, asks the user for confirmation and applies a proposal only after their button click.
Always respond as a single JSON object without Markdown:
{"reply":"visible Chinese reply","state":"thinking|running|analyzing|building|searching|permission|celebrating|failed|idle|attention","proposal":null}
For a reminder proposal, replace proposal with:
{"action":"create_reminder","title":"...","due_at":"YYYY-MM-DD HH:MM"}
or {"action":"update_reminder","task_id":"...","title":"optional","due_at":"optional YYYY-MM-DD HH:MM"}
or {"action":"cancel_reminder","task_id":"..."}.
Use task_id only from the supplied current reminder list. If a target is unclear, ask a follow-up question with proposal set to null.
"""


class HermesError(RuntimeError):
    pass


@dataclass
class HermesClient:
    settings: Settings
    bridge: LocalHermesBridge | None = None
    session_id: str = ""

    def __post_init__(self) -> None:
        if not self.session_id:
            self.session_id = f"desktop-pet-{uuid.uuid4().hex}"

    def chat(self, message: str, reminder_context: list[dict[str, str]] | None = None) -> ButlerReply:
        system_prompt = self._system_prompt(reminder_context or [])
        if self.bridge is not None and self.bridge.wait_until_ready():
            return self._chat_http(message, system_prompt=system_prompt, base_url=self.bridge.base_url, api_key=self.bridge.api_key, local_bridge=True)
        if self.settings.hermes_backend == "http":
            return self._chat_http(message, system_prompt=system_prompt)
        if self.settings.hermes_backend == "cli":
            return self._chat_cli(message, system_prompt=system_prompt)
        raise HermesError("\u672a\u627e\u5230\u53ef\u7528\u7684 Hermes \u8fde\u63a5\u3002")

    def _chat_http(
        self,
        message: str,
        *,
        system_prompt: str,
        base_url: str | None = None,
        api_key: str | None = None,
        local_bridge: bool = False,
    ) -> ButlerReply:
        headers = {"Content-Type": "application/json"}
        resolved_api_key = self.settings.hermes_api_key if api_key is None else api_key
        if resolved_api_key:
            headers["Authorization"] = f"Bearer {resolved_api_key}"
        if local_bridge:
            headers["X-Hermes-Session-Id"] = self.session_id
            headers["X-Hermes-Session-Key"] = self.session_id
        payload = {
            "model": self.settings.hermes_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            "temperature": 0.8,
        }
        endpoint = f"{(base_url or self.settings.hermes_base_url).rstrip('/')}/chat/completions"
        last_error: Exception | None = None
        # A local Hermes gateway can briefly reject a request while its model
        # worker is waking up. One small retry makes that transparent without
        # duplicating user-visible side effects (this protocol only proposes).
        for attempt in range(2):
            try:
                response = httpx.post(endpoint, headers=headers, json=payload, timeout=self.settings.hermes_timeout_seconds)
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return self._validate_content(content)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code < 500 or attempt == 1:
                    break
            except (httpx.TimeoutException, httpx.TransportError, KeyError, IndexError, TypeError, ValueError) as exc:
                last_error = exc
                if attempt == 1:
                    break
            time.sleep(0.35)

        if isinstance(last_error, httpx.HTTPStatusError):
            raise HermesError(f"\u672c\u673a Hermes \u6682\u65f6\u65e0\u6cd5\u5904\u7406\u8bf7\u6c42\uff08HTTP {last_error.response.status_code}\uff09\u3002\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002") from last_error
        raise HermesError("\u672c\u673a Hermes \u6682\u65f6\u6ca1\u6709\u54cd\u5e94\uff08\u5df2\u81ea\u52a8\u91cd\u8bd5\u4e00\u6b21\uff09\u3002\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002") from last_error

    def _chat_cli(self, message: str, *, system_prompt: str) -> ButlerReply:
        prompt = f"{system_prompt}\n\nUser message: {message}\nAssistant response:"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                [str(self.settings.hermes_cli_python), str(self.settings.hermes_cli_launcher), "--oneshot", prompt],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.settings.hermes_timeout_seconds,
                creationflags=creationflags,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HermesError(f"\u672c\u673a Hermes \u8c03\u7528\u5931\u8d25\uff1a{exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or "\u672a\u77e5\u9519\u8bef"
            raise HermesError(f"\u672c\u673a Hermes \u8fd4\u56de\u9519\u8bef\uff1a{detail[:160]}")
        return self._validate_content(result.stdout)

    @staticmethod
    def _validate_content(content: object) -> ButlerReply:
        try:
            return parse_butler_reply(content)
        except ValueError as exc:
            raise HermesError("Hermes \u8fd4\u56de\u4e86\u7a7a\u56de\u590d\u3002") from exc

    @staticmethod
    def _system_prompt(reminders: list[dict[str, str]]) -> str:
        if not reminders:
            return SYSTEM_PROMPT + "\nCurrent reminder list: []"
        return SYSTEM_PROMPT + "\nCurrent reminder list: " + json.dumps(reminders, ensure_ascii=False)
