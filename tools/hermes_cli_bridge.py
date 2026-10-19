"""OpenAI-compatible host bridge from Resume Studio to the current Hermes CLI.

Modern Hermes releases use ``hermes gateway`` for messaging and no longer expose
the legacy generation API on port 8642. This adapter preserves Resume Studio's
existing OpenAI chat-completions integration by translating calls to ``hermes -z``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_env(ROOT / ".env")

# Loopback is the safe default. When Resume Studio runs in Docker/WSL, launch
# with HERMES_BRIDGE_HOST set to that private virtual adapter's host address.
HOST = os.getenv("HERMES_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.getenv("HERMES_BRIDGE_PORT", "8642"))
API_KEY = os.getenv("HERMES_API_KEY", os.getenv("API_SERVER_KEY", ""))
HERMES_EXE = os.getenv("HERMES_CLI", "hermes")
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "300"))
LOG_PATH = ROOT / "tmp" / "hermes_bridge.log"


def _log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n"
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(line)


def _prompt(messages: list[dict]) -> str:
    parts: list[str] = []
    for message in messages:
        role = str(message.get("role") or "user").upper()
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "\n".join(
                str(item.get("text") or "") if isinstance(item, dict) else str(item)
                for item in content
            )
        parts.append(f"{role}:\n{content}")
    return "\n\n".join(parts)


# Every request runs as one isolated one-shot: --safe-mode drops user plugins,
# MCP servers, memory and rules, and "-t file" exposes a single toolset. Together
# they halve Hermes' fixed per-call prompt overhead (~11.5k -> ~5.5k tokens).
BASE_ARGS = ["--ignore-rules", "--safe-mode", "-t", "file"]
# Windows CreateProcess caps the whole command line at 32,767 UTF-16 units. Pass
# the prompt inline whenever the quoted command fits, so Hermes answers in one
# model call; the read-a-file route costs several agent turns (measured: 6 calls
# and ~117k tokens versus 2 calls and ~13k tokens for a full application draft).
CMDLINE_LIMIT = 31_000


def _cmdline_len(cmd: list[str]) -> int:
    return len(subprocess.list2cmdline(cmd).encode("utf-16-le")) // 2


def _read_usage(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _run_hermes(messages: list[dict]) -> tuple[str, dict]:
    prompt = _prompt(messages)
    prompt_path: Path | None = None
    usage_dir = ROOT / "tmp" / "hermes-prompts"
    usage_dir.mkdir(parents=True, exist_ok=True)
    usage_path = usage_dir / f"usage-{uuid.uuid4().hex}.json"
    base = [HERMES_EXE, *BASE_ARGS, "--usage-file", str(usage_path)]
    inline = base + ["-z", prompt]
    # Too long for one command line: place the request in a private temporary
    # file and let Hermes read it with its local file tool.
    if _cmdline_len(inline) > CMDLINE_LIMIT:
        prompt_dir = ROOT / "tmp" / "hermes-prompts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".txt", prefix="request-",
            dir=prompt_dir, delete=False,
        )
        try:
            handle.write(prompt)
        finally:
            handle.close()
        prompt_path = Path(handle.name)
        relative = prompt_path.relative_to(ROOT).as_posix()
        cli_prompt = (
            f"Read the complete request in {relative}. Follow its SYSTEM and USER "
            "instructions exactly. Use no tools except reading that one file. Return "
            "only the requested final response, with no commentary."
        )
        cmd = base + ["-z", cli_prompt]
    else:
        cmd = inline
    started = time.perf_counter()
    try:
        try:
            result = subprocess.run(
                cmd,
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        finally:
            if prompt_path is not None:
                prompt_path.unlink(missing_ok=True)
            usage = _read_usage(usage_path)
            usage_path.unlink(missing_ok=True)
            total = usage.get("total_including_auxiliary") or {}
            _log(
                f"request route={'file' if prompt_path else 'inline'} chars={len(prompt)} "
                f"secs={time.perf_counter() - started:.1f} api_calls={total.get('api_calls', '?')} "
                f"in={usage.get('input_tokens', '?')} out={usage.get('output_tokens', '?')} "
                f"total_tokens={total.get('total_tokens', '?')}"
            )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Hermes CLI was not found: {HERMES_EXE}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Hermes CLI timed out after {TIMEOUT:.0f}s") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "unknown Hermes CLI error").strip()
        raise RuntimeError(detail[-2000:])
    output = (result.stdout or "").strip()
    if not output:
        raise RuntimeError("Hermes CLI returned an empty response")
    return output, usage


class Handler(BaseHTTPRequestHandler):
    server_version = "ResumeStudioHermesBridge/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stdout.write("[hermes-bridge] " + (fmt % args) + "\n")
        sys.stdout.flush()

    def _send(self, status: int, payload: dict, retry_after: int | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if retry_after is not None:
            self.send_header('Retry-After', str(retry_after))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return not API_KEY or self.headers.get("Authorization", "") == f"Bearer {API_KEY}"

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/v1/models":
            self._send(404, {"error": {"message": "Not found"}})
        elif not self._authorized():
            self._send(401, {"error": {"message": "Unauthorized"}})
        else:
            self._send(200, {"object": "list", "data": [{
                "id": "hermes-agent", "object": "model", "owned_by": "local"
            }]})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._send(404, {"error": {"message": "Not found"}})
            return
        if not self._authorized():
            self._send(401, {"error": {"message": "Unauthorized"}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length) or b"{}")
            content, usage = _run_hermes(request.get("messages") or [])
            prompt_tokens = int(usage.get("input_tokens") or 0)
            completion_tokens = int(usage.get("output_tokens") or 0)
            self._send(200, {
                "id": f"chatcmpl-{uuid.uuid4().hex}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": request.get("model") or "hermes-agent",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            })
        except Exception as exc:
            _log(f"request failed: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
            message = str(exc)
            if re.search(r'rate.limit|usage limit|HTTP 429', message, re.I):
                minutes = re.search(r'(?:~|in\s+)(\d+)\s*(?:min|m\b)', message, re.I)
                delay = max(60, int(minutes.group(1)) * 60 + 60) if minutes else 900
                self._send(429, {"error": {"message": message}}, retry_after=delay)
            else:
                self._send(502, {"error": {"message": message}})


def main() -> None:
    if not shutil.which(HERMES_EXE) and not Path(HERMES_EXE).exists():
        raise SystemExit(f"Hermes CLI not found: {HERMES_EXE}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    _log(f"bridge started on {HOST}:{PORT} pid={os.getpid()}")
    print(f"Hermes CLI bridge listening on http://{HOST}:{PORT}/v1", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
