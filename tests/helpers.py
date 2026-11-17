from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import StdioServerParameters


def server_params(home: Path, extra_env: dict[str, str] | None = None) -> StdioServerParameters:
    env = {"XN_BRIDGE_HOME": str(home)}
    env.update(extra_env or {})
    return StdioServerParameters(command=sys.executable, args=["-m", "xnbridge.server"], env=env)


async def call(client, name: str, args: dict[str, Any] | None = None) -> tuple[bool, Any]:
    r = await client.call_tool(name, args or {})
    if r.structured_content is not None:
        return r.is_error, r.structured_content
    text = r.content[0].text if r.content else ""
    try:
        return r.is_error, json.loads(text)
    except json.JSONDecodeError:
        return r.is_error, text


def error_payload(data: Any) -> dict[str, Any]:
    text = data if isinstance(data, str) else json.dumps(data)
    start = text.find("{")
    return json.loads(text[start:]) if start >= 0 else {}


def listening_sockets(pid: int) -> list[str]:
    inodes = set()
    fd_dir = Path(f"/proc/{pid}/fd")
    for fd in fd_dir.iterdir():
        try:
            target = os.readlink(fd)
        except OSError:
            continue
        if target.startswith("socket:["):
            inodes.add(target[8:-1])
    found = []
    for name, listen_only in (("tcp", True), ("tcp6", True), ("udp", False), ("udp6", False)):
        path = Path(f"/proc/net/{name}")
        if not path.exists():
            continue
        for line in path.read_text().splitlines()[1:]:
            cols = line.split()
            if len(cols) < 10 or cols[9] not in inodes:
                continue
            if listen_only and cols[3] != "0A":
                continue
            found.append(f"{name}:{cols[1]}")
    return found
