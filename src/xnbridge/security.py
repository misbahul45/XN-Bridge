from __future__ import annotations

import fnmatch
import hashlib
import ipaddress
import json
import os
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from .errors import PolicyDenied, ValidationFailed

Resolver = Callable[[str], list[str]]


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_obj(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({i[4][0] for i in infos})


_NUMERIC_HOST = re.compile(r"^(0x[0-9a-f]+|\d+)(\.(0x[0-9a-f]+|\d+)){0,3}$", re.I)


def _normalize_numeric_host(host: str) -> str | None:
    if not _NUMERIC_HOST.match(host):
        return None
    try:
        return socket.inet_ntoa(socket.inet_aton(host))
    except OSError:
        return None


def _addr_is_public(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return bool(ip.is_global) and not ip.is_multicast


@dataclass
class UrlCheck:
    ok: bool
    reason: str
    origin: str = ""
    host: str = ""
    addresses: tuple[str, ...] = ()


_BLOCKED_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home.arpa", ".corp")


def check_url(url: str, resolver: Resolver | None = None, *, resolve: bool = True) -> UrlCheck:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return UrlCheck(False, "unparseable url")
    if parts.scheme not in ("http", "https"):
        return UrlCheck(False, f"scheme '{parts.scheme}' not allowed")
    if parts.username or parts.password or "@" in (parts.netloc or ""):
        return UrlCheck(False, "credentials in url not allowed")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return UrlCheck(False, "missing host")
    try:
        port = parts.port
    except ValueError:
        return UrlCheck(False, "invalid port")
    origin = f"{parts.scheme}://{host}" + (f":{port}" if port else "")
    if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
        return UrlCheck(False, "local hostname blocked", origin, host)
    numeric = _normalize_numeric_host(host)
    literal = numeric or host
    try:
        ipaddress.ip_address(literal.strip("[]"))
        is_literal = True
    except ValueError:
        is_literal = False
    if is_literal:
        if not _addr_is_public(literal.strip("[]")):
            return UrlCheck(False, "non-public ip literal blocked", origin, host)
        return UrlCheck(True, "ok", origin, host, (literal,))
    if not resolve:
        return UrlCheck(True, "ok (unresolved)", origin, host)
    try:
        addrs = (resolver or default_resolver)(host)
    except OSError as e:
        return UrlCheck(False, f"dns resolution failed: {e}", origin, host)
    if not addrs:
        return UrlCheck(False, "no addresses", origin, host)
    bad = [a for a in addrs if not _addr_is_public(a)]
    if bad:
        return UrlCheck(False, f"resolves to non-public address {bad[0]}", origin, host, tuple(addrs))
    return UrlCheck(True, "ok", origin, host, tuple(addrs))


def require_public_url(url: str, resolver: Resolver | None = None) -> UrlCheck:
    c = check_url(url, resolver)
    if not c.ok:
        raise PolicyDenied(f"url rejected: {c.reason}", details={"url_host": c.host})
    return c


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValidationFailed("target must be an http(s) url with a host")
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname.lower()}{port}"


_SENSITIVE_PARTS = (
    ".ssh", ".gnupg", ".aws", ".kube", ".docker", ".claude", ".codex", ".cursor", ".gemini",
    ".config/gcloud", ".config/gh", ".netrc", ".npmrc", ".pypirc", ".git-credentials", ".xninetzy",
    "approver.key.enc", "id_rsa", "id_ed25519",
)
_SENSITIVE_NAMES = ("*.pem", "*.key", ".env", ".env.*", "credentials*.json", "*.kdbx", "*.p12", "*.pfx")
_SENSITIVE_ROOTS = ("/etc", "/proc", "/sys", "/dev", "/root", "/boot", "/var/lib", "/run")


def is_sensitive_path(path: Path) -> str | None:
    try:
        resolved = path.resolve()
    except OSError:
        return "unresolvable path"
    text = resolved.as_posix()
    for root in _SENSITIVE_ROOTS:
        if text == root or text.startswith(root + "/"):
            return f"under {root}"
    for part in _SENSITIVE_PARTS:
        if f"/{part}/" in text + "/" or text.endswith("/" + part):
            return f"sensitive location {part}"
    for pat in _SENSITIVE_NAMES:
        if fnmatch.fnmatch(resolved.name, pat):
            return f"sensitive file pattern {pat}"
    return None


def safe_join(base: Path, rel: str | Path) -> Path:
    base_r = base.resolve()
    cand = (base_r / rel).resolve()
    if cand != base_r and base_r not in cand.parents:
        raise PolicyDenied("path escapes the allowed directory", details={"rel": str(rel)})
    return cand


def check_read_path(path: str | Path, allowed_roots: list[Path]) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise ValidationFailed("path must be absolute")
    resolved = p.resolve()
    reason = is_sensitive_path(resolved)
    if reason:
        raise PolicyDenied(f"path rejected: {reason}")
    if allowed_roots and not any(resolved == r.resolve() or r.resolve() in resolved.parents for r in allowed_roots):
        raise PolicyDenied("path is outside the allowed roots")
    return resolved


_INJECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("override_instructions", re.compile(r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|system)\b.{0,30}\b(instruction|prompt|rule|polic)", re.I | re.S)),
    ("role_hijack", re.compile(r"\b(you are now|act as|new instructions?:|system prompt|developer message)\b", re.I)),
    ("self_approval", re.compile(r"\b(approved|authorized|authorised|consent|user_approved|is_approved)[\"']?\s*[:=]\s*[\"']?(true|yes|1)\b", re.I)),
    ("approval_claim", re.compile(r"\b(the user (has )?(approved|authori[sz]ed|consented)|pre-?approved|auto-?approve)\b", re.I)),
    ("tool_call_syntax", re.compile(r"(<\s*/?\s*(tool_call|function_call|invoke|antml)[^>]*>|\"?(tool_name|function_call)\"?\s*:)", re.I)),
    ("exfiltration", re.compile(r"\b(send|post|upload|email|forward)\b.{0,50}\b(cv|resume|password|token|api[_ -]?key|credentials|\.ssh|private key)\b", re.I | re.S)),
    ("shell_exec", re.compile(r"(\bcurl\b[^\n]{0,80}\|\s*(ba)?sh\b|\brm\s+-rf\b|\bsudo\b|\bchmod\s+[0-7]{3,4}\b)", re.I)),
    ("policy_change", re.compile(r"\b(disable|turn off|bypass|skip)\b.{0,30}\b(approval|verification|safety|policy|check|captcha)\b", re.I | re.S)),
]


def scan_untrusted(text: str, limit: int = 200_000) -> list[str]:
    sample = text[:limit]
    return [name for name, pat in _INJECTION_PATTERNS if pat.search(sample)]


_SECRET_PATTERNS = [
    re.compile(r"\bGOCSPX-[A-Za-z0-9_-]+"),
    re.compile(r"\bya29\.[A-Za-z0-9._-]+"),
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9_\-\.=/+]{12,}"),
    re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_\-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|client[_-]?secret|secret|token|password|passwd|bearer)\b['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.=/+]{8,}"),
    re.compile(r"(?i)([?&](api[_-]?key|token|access_token|key|secret|signature|sig)=)[^&\s]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]


def redact(text: str) -> str:
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub(lambda m: (m.group(1) + "<redacted>") if m.lastindex else "<redacted>", out)
    return out


def redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparseable>"
    host = parts.hostname or ""
    return f"{parts.scheme}://{host}{parts.path}" if parts.scheme else url


@dataclass(frozen=True)
class RiskInfo:
    risk: str
    source: str
    maybe_external: bool = False
    rule: str | None = None


_READ_VERBS = ("get_", "list_", "search_", "read_", "find_", "inspect_", "fetch", "query", "describe", "status", "info", "check_", "resolve_", "preview")


class RiskClassifier:
    def __init__(self, policy: dict[str, Any]):
        self.rules = policy.get("risk", [])
        self.heuristic_servers = set(policy.get("trust", {}).get("read_heuristic_servers", []))

    def classify(self, server: str, tool: str, stage_risk: str | None = None) -> RiskInfo:
        info = self._classify(server, tool)
        if info.maybe_external and stage_risk == "EXTERNAL_WRITE":
            return RiskInfo("EXTERNAL_WRITE", info.source, True, info.rule)
        return info

    def _classify(self, server: str, tool: str) -> RiskInfo:
        for rule in self.rules:
            if fnmatch.fnmatch(server, rule["server"]) and fnmatch.fnmatch(tool, rule["tool"]):
                return RiskInfo(rule["risk"], "policy", bool(rule.get("maybe_external", False)), f"{rule['server']}:{rule['tool']}")
        low = tool.lower()
        if server in self.heuristic_servers and low.startswith(_READ_VERBS):
            return RiskInfo("READ", "heuristic")
        return RiskInfo("EXTERNAL_WRITE", "fail_closed")


def requires_approval(risk: str) -> bool:
    return risk == "EXTERNAL_WRITE"


def mem_available_mb() -> int | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def self_rss_mb() -> int | None:
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def cpu_load_per_core() -> float | None:
    try:
        return os.getloadavg()[0] / (os.cpu_count() or 1)
    except (AttributeError, OSError):
        return None


def file_mode_private(path: Path) -> bool:
    try:
        return (os.stat(path).st_mode & 0o077) == 0
    except OSError:
        return False
