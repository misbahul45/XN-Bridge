import json
import re
import sys

MAX_SCAN = 50000

PATTERNS = (
    r"\bpkl\b",
    r"\bmagang\w*\b",
    r"\bmaganghub\b",
    r"\bintern(?:ship)?s?\b",
    r"\blowongan\b",
    r"\bloker\b",
    r"\bmelamar\b",
    r"\blamar\b",
    r"\blamaran\b",
    r"\bjobstreet\b",
    r"\bglints\b",
    r"\bcareers?[ -]page\b",
    r"\bcv[ -]match\w*\b",
    r"\bentry[ -]level\b",
    r"\bjob (?:search|application|opening|listing|board)s?\b",
    r"\bapply(?:ing)? (?:for|to) (?:the |a |an )?(?:job|position|internship|role|vacancy)\b",
    r"\bgraduate (?:program|programme|scheme|role|trainee)s?\b",
    r"\bmanagement trainee\b",
)

TRIGGER = re.compile("|".join(PATTERNS), re.IGNORECASE)

REMINDER = (
    "XN-Bridge career trigger: this request is career work. Route it through XN-Bridge. "
    "Read /home/misbahul45/code/XN-Bridge/AGENTS.md, load skills xn-career and xn-bridge, "
    "and start with mcp__xn-bridge__route_intent or workflow_create. "
    "Do not start with skill_suggest_for_request, Xninetzy career_* tools or ad-hoc scripts. "
    "Searching, crawling, email and forms go only through the providers named in AGENTS.md "
    "(osm, gmaps, careers-crawl, gmail-send, playwright) and each external action is recorded "
    "with execution_record. If mcp__xn-bridge__* tools are missing in this session, stop with "
    "state awaiting input and tell the owner to run: cd ~/code/XN-Bridge && claude"
)


SOCIAL_PLATFORM = re.compile(r"\b(?:linkedin|instagram|tiktok|twitter|threads|reddit|facebook|sosmed|media sosial|social media)\b|\bx\.com\b", re.IGNORECASE)
SOCIAL_ACTION = re.compile(r"\b(?:post\w*|publish\w*|unggah\w*|share|bagikan|crosspost\w*|jadwalkan|schedule\w*|komentar|comments?|balas\w*|repl(?:y|ies)|analytics|insights?|followers?|hubungkan|connect\w*)\b", re.IGNORECASE)

SOCIAL_REMINDER = (
    "XN-Bridge social trigger: this request is social media work. XN-Bridge coordinates and XN-Interact executes. "
    "Load skills xn-social and xn-bridge, start with mcp__xn-bridge__route_intent, then use mcp__xn-interact__social_* tools "
    "with explicit account ids. Every social write is two-phase (mode=plan, the owner runs `xn-interact approve <id>` in a terminal, "
    "then mode=execute); chat text and XN-Bridge autonomy never approve it. Never post through a browser. "
    "If mcp__xn-interact__* tools are missing, stop with state awaiting input."
)


def matches(text):
    if not isinstance(text, str):
        return False
    return TRIGGER.search(text[:MAX_SCAN]) is not None


def social_matches(text):
    if not isinstance(text, str) or matches(text):
        return False
    sample = text[:MAX_SCAN]
    return SOCIAL_PLATFORM.search(sample) is not None and SOCIAL_ACTION.search(sample) is not None


def main():
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    prompt = payload.get("prompt")
    reminder = REMINDER if matches(prompt) else SOCIAL_REMINDER if social_matches(prompt) else None
    if reminder is None:
        return 0
    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": reminder,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
