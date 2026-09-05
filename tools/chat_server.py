"""Small browser chatbot for an llmwiki knowledge base.

The LLM is deliberately loaded through a user-supplied Python module. Set
CHAT_LLM_MODULE to a module importable on PYTHONPATH and CHAT_LLM_FUNCTION to
its callable. The callable receives OpenAI-shaped messages and returns text
(or a response object with a ``text``/``content`` field).
"""

from __future__ import annotations

import asyncio
import importlib
import json
import mimetypes
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
UI_FILE = ROOT / "tools" / "chat.html"
PORT = int(os.environ.get("CHAT_PORT", "8787"))
LLMWIKI_BIN = os.environ.get("LLMWIKI_BIN", "llmwiki")
CONTEXT_CHARS = int(os.environ.get("CHAT_CONTEXT_CHARS", "60000"))
HISTORY_TURNS = int(os.environ.get("CHAT_HISTORY_TURNS", "6"))
RETRIEVAL_TIMEOUT = int(os.environ.get("CHAT_RETRIEVAL_TIMEOUT_SECONDS", "60"))
LLM_MODULE = os.environ.get("CHAT_LLM_MODULE")
LLM_FUNCTION = os.environ.get("CHAT_LLM_FUNCTION", "generate")


def json_error(message: str, status: int = 400) -> tuple[int, dict]:
    return status, {"error": message}


def retrieve(query: str) -> object:
    try:
        completed = subprocess.run(
            [LLMWIKI_BIN, "context", query, "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=RETRIEVAL_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Knowledge-base retrieval failed: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "llmwiki returned a non-zero exit code"
        raise RuntimeError(detail)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("llmwiki returned invalid JSON") from exc


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := _text(item)))
    if isinstance(value, dict):
        preferred = ("content", "text", "body", "summary", "excerpt", "snippet")
        selected = [value[key] for key in preferred if key in value]
        return "\n".join(part for item in selected if (part := _text(item)))
    return ""


def context_text(value: object) -> str:
    """Preserve useful JSON fields without depending on one llmwiki version."""
    if isinstance(value, dict):
        for key in ("results", "pages", "matches", "context", "items"):
            if key in value:
                value = value[key]
                break
    if isinstance(value, list):
        chunks = []
        for index, item in enumerate(value, 1):
            if isinstance(item, dict):
                label = item.get("title") or item.get("path") or f"Result {index}"
                chunks.append(f"[{label}]\n{_text(item)}")
            else:
                chunks.append(_text(item))
        return "\n\n".join(chunk for chunk in chunks if chunk)
    return _text(value)


def load_generator():
    if not LLM_MODULE:
        raise RuntimeError(
            "Set CHAT_LLM_MODULE to the sanctioned Python LLM adapter module"
        )
    module = importlib.import_module(LLM_MODULE)
    generator = getattr(module, LLM_FUNCTION, None)
    if not callable(generator):
        raise RuntimeError(
            f"{LLM_MODULE}.{LLM_FUNCTION} is not an importable callable"
        )
    return generator


def generate(messages: list[dict]) -> str:
    result = load_generator()(messages)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            result = choices[0].get("message", {}).get("content", "")
        else:
            result = result.get("text") or result.get("content") or ""
    else:
        result = getattr(result, "text", None) or getattr(result, "content", None) or ""
    if not isinstance(result, str) or not result.strip():
        raise RuntimeError("The configured LLM adapter returned no text")
    return result.strip()


def chat(payload: dict) -> dict:
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string")
    history = payload.get("history", [])
    if not isinstance(history, list):
        raise ValueError("history must be an array")
    history = [
        item for item in history[-HISTORY_TURNS:]
        if isinstance(item, dict)
        and item.get("role") in ("user", "assistant")
        and isinstance(item.get("content"), str)
    ]
    retrieved = retrieve(message)
    context = context_text(retrieved)[:CONTEXT_CHARS]
    if not context:
        return {"answer": "The knowledge base returned no relevant context.", "sources": []}
    messages = [
        {
            "role": "system",
            "content": (
                "Answer only from the supplied knowledge-base context. Be concise. "
                "Cite the relevant page title or [page N] marker when present. "
                "If the context does not answer the question, say so plainly.\n\n"
                f"KNOWLEDGE-BASE CONTEXT:\n{context}"
            ),
        },
        *history,
        {"role": "user", "content": message.strip()},
    ]
    return {"answer": generate(messages), "sources": retrieved}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: object, content_type: str = "application/json"):
        encoded = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, UI_FILE.read_text(), "text/html; charset=utf-8")
        else:
            self._send(404, {"error": "Not found"}, "application/json")

    def do_POST(self):
        if urlparse(self.path).path != "/api/chat":
            self._send(404, {"error": "Not found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 128_000:
                raise ValueError("request is too large")
            payload = json.loads(self.rfile.read(size))
            response = chat(payload)
            self._send(200, response)
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            self._send(400, {"error": str(exc)})
        except Exception:
            self.log_error("Unexpected chatbot failure")
            self._send(500, {"error": "The chatbot could not complete the request"})

    def log_message(self, format, *args):
        print(f"[chat] {format % args}")


if __name__ == "__main__":
    print(f"Chatbot listening at http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
