"""Async runtime helper — select the fastest available event loop.

uvloop is a libuv-backed drop-in for asyncio's event loop (~1.6x faster on loop
primitives). It's absent on Windows and in minimal envs, so selection is
best-effort and falls back to stock asyncio.

The web app passes :func:`active_loop_name` to uvicorn (``--loop``) so the ASGI
server runs on uvloop when available.
"""

from __future__ import annotations


def active_loop_name() -> str:
    """``"uvloop"`` if uvloop is importable, else ``"asyncio"``. Never raises."""
    try:
        import uvloop  # noqa: F401
    except ImportError:
        return "asyncio"
    return "uvloop"
