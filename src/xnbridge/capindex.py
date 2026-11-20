from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

SYNONYMS: dict[str, str] = {
    "cari": "search", "carikan": "search", "mencari": "search", "temukan": "search", "find": "search", "lookup": "search", "look": "search", "search": "search", "telusuri": "search",
    "tempat": "place", "lokasi": "place", "location": "place", "locations": "place", "alamat": "place", "address": "place", "peta": "place", "map": "place", "maps": "place", "places": "place", "nearby": "place", "terdekat": "place", "sekitar": "place",
    "kantor": "office", "offices": "office", "perusahaan": "company", "companies": "company",
    "baca": "read", "membaca": "read", "lihat": "read", "read": "read", "reads": "read", "view": "read", "isi": "content", "konten": "content", "teks": "text",
    "ambil": "fetch", "fetch": "fetch", "download": "fetch", "unduh": "fetch",
    "halaman": "page", "pages": "page", "situs": "web", "website": "web", "site": "web", "internet": "web", "online": "web",
    "dokumen": "document", "documents": "document", "file": "document", "berkas": "document", "pdf": "document", "docx": "document",
    "ekstrak": "extract", "convert": "extract", "konversi": "extract", "ubah": "extract", "parse": "extract",
    "buat": "generate", "bikin": "generate", "create": "generate", "generate": "generate", "export": "generate", "render": "generate",
    "paper": "paper", "papers": "paper", "jurnal": "paper", "journal": "paper", "journals": "paper", "artikel": "paper", "academic": "paper", "akademik": "paper", "scholarly": "paper",
    "kode": "code", "fungsi": "code", "function": "code", "functions": "code", "class": "code", "symbol": "code", "callers": "code", "repository": "code", "repo": "code",
    "kirim": "send", "send": "send", "email": "email", "emails": "email", "surel": "email", "gmail": "email", "inbox": "email", "balasan": "reply", "replies": "reply",
    "form": "form", "formulir": "form", "isikan": "fill", "fill": "fill", "lampirkan": "upload", "attach": "upload", "upload": "upload",
    "browser": "browser", "screenshot": "browser", "snapshot": "inspect", "inspect": "inspect", "periksa": "inspect",
    "crawl": "crawl", "jelajahi": "crawl", "workflow": "workflow", "checkpoint": "workflow", "evidence": "evidence", "bukti": "evidence",
}

ACTIONS = frozenset({"search", "read", "fetch", "extract", "generate", "send", "fill", "upload", "crawl", "inspect", "reply", "publish", "list"})
OBJECTS = frozenset({"place", "office", "company", "page", "web", "document", "paper", "code", "email", "form", "browser", "workflow", "evidence", "text", "content", "markdown", "listing", "board"})

STOP = frozenset(
    "a an the of to in on at for and or with by from is are be this that it my me i you your our we please tolong saya aku kamu ini itu yang di ke dari dan atau untuk dengan pada ada apa bisa mau ingin".split()
)


def tokens(text: str) -> list[str]:
    out: list[str] = []
    for raw in re.findall(r"[a-z0-9]+", text.lower()):
        if raw in STOP or len(raw) < 2:
            continue
        t = SYNONYMS.get(raw, raw)
        if t == raw and len(t) > 4 and t.endswith("s"):
            t = SYNONYMS.get(t[:-1], t[:-1])
        out.append(t)
    return out


@dataclass(frozen=True)
class CapHit:
    capability: str
    score: float
    matched: tuple[str, ...]
    strong: tuple[str, ...] = ()

    @property
    def confident(self) -> bool:
        m = set(self.matched)
        return bool(m & ACTIONS) and bool(m & OBJECTS or set(self.strong) - ACTIONS)


class CapabilityIndex:
    def __init__(self, capabilities: dict[str, dict[str, Any]]):
        self.docs: dict[str, dict[str, float]] = {}
        for cap, entry in capabilities.items():
            weights: dict[str, float] = {}
            for t in tokens(cap.replace(".", " ").replace("_", " ")):
                weights[t] = max(weights.get(t, 0.0), 2.0)
            for t in tokens(entry.get("description", "")):
                weights[t] = max(weights.get(t, 0.0), 1.0)
            for kw in entry.get("keywords", []):
                for t in tokens(str(kw)):
                    weights[t] = max(weights.get(t, 0.0), 1.5)
            for prov in entry.get("provider", []):
                for t in tokens(str(prov.get("tool", "")).replace("_", " ")):
                    weights.setdefault(t, 0.5)
            self.docs[cap] = weights
        n = max(len(self.docs), 1)
        df: dict[str, int] = {}
        for w in self.docs.values():
            for t in w:
                df[t] = df.get(t, 0) + 1
        self.idf = {t: math.log(1 + n / c) for t, c in df.items()}

    def search(self, text: str, k: int = 3) -> list[CapHit]:
        q = list(dict.fromkeys(tokens(text)))
        if not q:
            return []
        hits: list[CapHit] = []
        for cap, w in self.docs.items():
            matched = tuple(t for t in q if t in w)
            if not matched:
                continue
            score = sum(w[t] * self.idf.get(t, 0.0) for t in matched) / math.sqrt(len(q))
            hits.append(CapHit(cap, round(score, 3), matched, tuple(t for t in matched if w[t] >= 1.5)))
        hits.sort(key=lambda h: (-h.score, h.capability))
        return hits[:k]
