from __future__ import annotations

import html
import ipaddress
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "gclid", "fbclid", "ref", "ref_src", "source", "src", "gh_src", "lever-source", "lever-origin", "trk", "mc_cid", "mc_eid",
    "_hsenc", "_hsmi", "igshid", "yclid", "msclkid", "campaign", "referrer", "refid", "trackingid",
}
SECOND_LEVEL_SUFFIXES = {
    "co.id", "ac.id", "or.id", "go.id", "sch.id", "web.id", "my.id", "com.au", "co.uk", "ac.uk", "com.sg", "edu.sg", "com.my",
    "edu.my", "co.jp", "co.kr", "com.br", "co.in", "ac.in", "co.nz", "com.ph", "com.vn", "co.th", "ac.th", "com.hk", "com.cn",
    "com.tw", "co.za", "org.uk", "gov.uk", "edu.au", "org.au",
}
AGGREGATOR_DOMAINS = {
    "linkedin.com", "glints.com", "kalibrr.com", "jobstreet.com", "jobstreet.co.id", "indeed.com", "glassdoor.com", "facebook.com",
    "instagram.com", "twitter.com", "x.com", "github.com", "linktr.ee", "medium.com", "wellfound.com", "angel.co", "remoteok.com",
    "remoteok.io", "arbeitnow.com", "weworkremotely.com", "topkarir.com", "karir.com", "dealls.com", "talentics.id", "youtube.com",
    "tiktok.com", "bit.ly", "wa.me", "google.com", "forms.gle", "docs.google.com", "notion.site", "notion.so", "wordpress.com",
    "blogspot.com", "wixsite.com", "carrd.co",
}
LEGAL_FORMS = {
    "pt", "cv", "ud", "pd", "tbk", "persero", "ltd", "limited", "inc", "incorporated", "corp", "corporation", "co", "company",
    "llc", "llp", "gmbh", "ag", "plc", "sdn", "bhd", "pte", "pty", "bv", "sa", "srl", "kk", "oy", "ab", "as",
}


def normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"\([^)]*\)", " ", s.lower())
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    tokens = [t for t in s.split() if t]
    while tokens and tokens[0] in LEGAL_FORMS:
        tokens.pop(0)
    while tokens and tokens[-1] in LEGAL_FORMS:
        tokens.pop()
    return " ".join(tokens)


def registrable_domain(host: str) -> str:
    host = host.lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in SECOND_LEVEL_SUFFIXES:
        return ".".join(labels[-3:])
    if len(labels) >= 2:
        return ".".join(labels[-2:])
    return host


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def is_aggregator(domain: str) -> bool:
    d = registrable_domain(domain)
    return d in AGGREGATOR_DOMAINS or any(d.endswith("." + a) for a in AGGREGATOR_DOMAINS)


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")]
    query.sort()
    path = parts.path.rstrip("/") or "/"
    scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def html_to_text(raw: str, limit: int | None = None) -> str:
    if re.search(r"&lt;\s*/?\w", raw):
        raw = html.unescape(raw)
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h[1-6]>|</div>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s).strip()
    return s[:limit] if limit else s


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#.]{2,}", text.lower()))
