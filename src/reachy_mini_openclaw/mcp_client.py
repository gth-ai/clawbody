"""Minimal MCP stdio client, so the robot can query an MCP server directly.

Why hand-rolled rather than the `mcp` package: it depends on pydantic, and
this environment already pins pydantic to 2.12.3 because gradio caps it there
(see INSTALL-LOCAL.md). Adding another pydantic consumer risks breaking the
whole install to save ~80 lines. The stdio protocol is line-delimited JSON-RPC
and needs nothing more than asyncio.

Purpose: cut the wedding-data path from
    Realtime -> openclaw CLI -> gateway -> agent -> model turn -> MCP -> Postgres
down to
    Realtime -> MCP -> Postgres
which is the difference between ~20-115 s and ~1-3 s. The agent round trip
exists to *choose* a tool; the Realtime model already chose it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from typing import Any, Optional

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"

# Ceiling for one JSON-RPC line. Generous on purpose: the cost of being wrong
# is a dropped connection mid-conversation, the cost of being generous is
# nothing until a server actually sends that much.
MAX_MESSAGE_BYTES = 32 * 1024 * 1024


class McpStdioClient:
    """Speaks JSON-RPC over stdio to one MCP server subprocess."""

    def __init__(
        self,
        command: str,
        args: list[str],
        cwd: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> None:
        self.command = command
        self.args = args
        self.cwd = cwd
        self.env = env
        self.timeout = timeout

        self._proc: Optional[asyncio.subprocess.Process] = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        # Serialise writes: several tool calls can be in flight at once.
        self._write_lock = asyncio.Lock()
        self.tools: list[dict] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> bool:
        """Spawn the server, handshake, and cache its tool list."""
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                # The server logs to stderr; swallow it rather than let the
                # pipe fill up and block the process.
                stderr=asyncio.subprocess.DEVNULL,
                cwd=self.cwd,
                env={**os.environ, **(self.env or {})},
                # Own process group: launchers like `tsx` spawn a child node
                # process, and terminating only the parent leaves that child
                # running. This project already accumulated 557 such orphans
                # from the OpenClaw bridge; stop() signals the whole group.
                start_new_session=True,
                # One JSON-RPC message per line, and a single message can be
                # large — listing 186 guests with their tags, RSVPs and
                # partners runs well past asyncio's default 64 KiB line limit.
                # Past it readline() raises and the reader loop dies, which
                # surfaced as a bogus "MCP server closed".
                limit=MAX_MESSAGE_BYTES,
            )
        except Exception as e:
            logger.error("Could not spawn MCP server %s: %s", self.command, e)
            return False

        self._reader_task = asyncio.create_task(self._read_loop(), name="mcp-reader")

        try:
            await self._request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "clawbody", "version": "1.0.0"},
                },
            )
            await self._notify("notifications/initialized", {})
            result = await self._request("tools/list", {})
            self.tools = result.get("tools", []) or []
        except Exception as e:
            logger.error("MCP handshake failed: %s", e)
            await self.stop()
            return False

        logger.info("MCP server ready: %d tools from %s", len(self.tools), self.command)
        return True

    async def stop(self) -> None:
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
        if self._proc and self._proc.returncode is None:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(os.getpgid(self._proc.pid), sig)
                except ProcessLookupError:
                    break
                except Exception:
                    # No process group (should not happen with
                    # start_new_session) — fall back to the parent alone.
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                    break
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=5)
                    break
                except asyncio.TimeoutError:
                    continue  # escalate to SIGKILL
        self._proc = None

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    # ------------------------------------------------------------------
    # Tool calls
    # ------------------------------------------------------------------

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Call a tool and return its text content."""
        result = await self._request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        parts = [
            c.get("text", "")
            for c in result.get("content", [])
            if isinstance(c, dict) and c.get("type") == "text"
        ]
        text = "\n".join(p for p in parts if p)
        if result.get("isError"):
            return f"[refusé par le serveur] {text}" if text else "[erreur outil]"
        return text

    # ------------------------------------------------------------------
    # JSON-RPC plumbing
    # ------------------------------------------------------------------

    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # servers sometimes print stray lines
                mid = msg.get("id")
                fut = self._pending.pop(mid, None) if mid is not None else None
                if fut and not fut.done():
                    if "error" in msg:
                        fut.set_exception(
                            RuntimeError(str(msg["error"].get("message", msg["error"])))
                        )
                    else:
                        fut.set_result(msg.get("result", {}))
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug("MCP reader stopped: %s", e)
        finally:
            # Nothing will answer these any more.
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("MCP server closed"))
            self._pending.clear()

    async def _send(self, payload: dict) -> None:
        if not (self._proc and self._proc.stdin):
            raise RuntimeError("MCP server not running")
        async with self._write_lock:
            self._proc.stdin.write((json.dumps(payload) + "\n").encode())
            await self._proc.stdin.drain()

    async def _notify(self, method: str, params: dict) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _request(self, method: str, params: dict) -> dict:
        self._next_id += 1
        req_id = self._next_id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        await self._send(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        )
        try:
            return await asyncio.wait_for(fut, timeout=self.timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise RuntimeError(f"MCP call '{method}' timed out after {self.timeout}s")
