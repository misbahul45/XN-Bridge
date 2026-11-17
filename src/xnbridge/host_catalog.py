"""Explicit host-owned catalog refresh. This is an operator adapter, not a gateway."""
from __future__ import annotations

import json
import math
import time

from .discovery import ServerProbe, host_fingerprint
from .errors import Unavailable, ValidationFailed
from .host_api import CodexHost, host_probe
from .security import redact


def sync_host_catalog(bridge, specs, *, only=None, timeout=30, watch_seconds=0, poll_interval=2, host_factory=CodexHost, progress=None):
    if not all(math.isfinite(x) for x in (watch_seconds, poll_interval, timeout)) or not 0 <= watch_seconds <= 300 or poll_interval < 1 or timeout <= 0:
        raise ValidationFailed("host watch needs 0..300 seconds, interval >=1 and timeout >0")
    if watch_seconds and not only:
        raise ValidationFailed("bounded host watch requires explicit --only servers")
    by_name = {s.name: s for s in specs}
    wanted = list(dict.fromkeys(only or list(by_name)))
    if not wanted or set(wanted) - set(by_name):
        raise ValidationFailed("host sync needs configured server names")
    host = host_factory(servers=wanted)
    rounds = calls = invalidations = events = 0
    latest = {}
    changes = {"new": set(), "changed": set(), "gone": set()}
    fp = host_fingerprint(specs)
    started = time.monotonic()
    try:
        host.start(timeout=timeout)
        deadline = time.monotonic() + watch_seconds
        while True:
            probes = []
            for name in wanted:
                if progress:
                    progress(name)
                t0 = time.monotonic()
                try:
                    rows = host.inventory(name, timeout=timeout)
                    calls += 1
                    matching = [r for r in rows if r.get("name") == name]
                    if len(matching) != 1:
                        raise ValidationFailed("host did not return exactly one selected provider")
                    probe = host_probe(matching[0], by_name[name])
                except (Unavailable, ValidationFailed) as e:
                    probe = ServerProbe(name, by_name[name].transport, "FAILED", detail=redact(str(e))[:300])
                probe.elapsed_ms = round((time.monotonic() - t0) * 1000)
                probes.append(probe)
            pending, host.notifications = host.notifications, []
            for event in pending:
                if event.get("name") in wanted:
                    events += 1
                    invalidations += bridge.registry.invalidate(event["name"], "native host startup status changed")
            delta = bridge.registry.ingest(probes, host_fp=fp, active_servers=list(by_name), source="codex-host-api")
            for key in changes:
                changes[key].update(delta[key])
            for probe in probes:
                latest[probe.server] = {"server": probe.server, "status": probe.status, "tools": len(probe.tools), "version": probe.server_version,
                                        "protocol": probe.protocol_version, "elapsed_ms": probe.elapsed_ms, "detail": probe.detail}
            rounds += 1
            if not watch_seconds or time.monotonic() >= deadline:
                break
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
    finally:
        host.close()
    return {"ok": all(s["status"] == "OK" for s in latest.values()), "source": "codex-host-api", "host_fingerprint": fp,
            "servers": list(latest.values()), "rounds": rounds, "inventory_calls": calls, "native_startup_events": events,
            "invalidated_servers": invalidations, "delta": {k: len(v) for k, v in changes.items()}, "model_calls": 0,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "protocol_observation": "negotiated MCP revision is not exposed by the host API; prior directly observed revisions are retained",
            "refresh": "native startup status invalidation plus bounded targeted polling; tool-list-change forwarding is not assumed"}
