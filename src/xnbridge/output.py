from __future__ import annotations

import json
import math
from typing import Any, Literal

from .artifacts import ArtifactStore

Level = Literal["SUMMARY", "DETAIL", "RAW_REFERENCE"]
LEVELS = ("SUMMARY", "DETAIL", "RAW_REFERENCE")


def estimate_tokens(obj: Any) -> int:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return math.ceil(len(text) / 4)


def shape(
    level: str,
    *,
    summary: dict[str, Any],
    detail: dict[str, Any] | None = None,
    raw: bytes | str | None = None,
    artifacts: ArtifactStore | None = None,
    workflow_id: str | None = None,
    kind: str = "raw",
    mime: str = "application/json",
) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": True, "level": level, **summary}
    if level == "SUMMARY":
        if detail is not None or raw is not None:
            out["more"] = "request level=DETAIL for fields or RAW_REFERENCE for the stored raw output"
        return out
    if level == "DETAIL":
        if detail:
            out["detail"] = detail
        if raw is not None:
            out["more"] = "request level=RAW_REFERENCE for the stored raw output"
        return out
    if level == "RAW_REFERENCE":
        if detail:
            out["detail"] = detail
        if raw is not None and artifacts is not None:
            out["raw_ref"] = artifacts.put(workflow_id, kind, raw, mime)
        return out
    raise ValueError(f"unknown level '{level}'")
