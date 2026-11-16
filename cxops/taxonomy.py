"""Reporting taxonomy: a shared Category > Topic picklist for tickets and survey responses.

The list is editable in the app (like picklist values in a CRM). Topics are never deleted, only
retired, so history keeps its labels. The model suggests one topic per item; a person can override it.
This runs as its own step, separate from the scored triage and survey pipelines, so it can't change them.
"""
import json
import os
import re
from pathlib import Path

from . import llm

FILE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "cx-ops-ai" / "taxonomy.json"

DEFAULT = {
    "Billing": ["Plans & pricing", "Charges & refunds", "Seats", "Cancellations & renewals"],
    "Account & Access": ["Login & passwords", "2FA & SSO", "Users & ownership"],
    "Integrations": ["QuickBooks", "Xero", "Calendar sync", "Zapier & API"],
    "Invoicing & Payments": ["Invoices & templates", "Reminders & late fees", "Online payments & payouts",
                             "Taxes & currency", "Client portal"],
    "Time & Reports": ["Time tracking & approvals", "Expenses & mileage", "Reports"],
    "Data": ["Import & export", "Privacy & compliance"],
    "Product Quality": ["Bugs & errors", "Outages & data loss", "Speed", "Mobile app"],
    "Product Feedback": ["Feature requests", "Ease of use", "Onboarding"],
    "Support Experience": ["Response time", "Staff praise"],
    "Other": ["Spam / not support", "General / other"],
}
FALLBACK = "general-other"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "topic"


def default_taxonomy() -> dict:
    return {"categories": [{"name": c, "topics": [{"id": slug(t), "name": t, "active": True} for t in ts]}
                           for c, ts in DEFAULT.items()]}


def load() -> dict:
    try:
        tax = json.loads(FILE.read_text(encoding="utf-8"))
        if tax.get("categories"):
            return tax
    except (OSError, ValueError):
        pass
    return default_taxonomy()


def save(tax: dict) -> dict:
    """Validate and store an edited list. Topics already in use can be retired but never removed."""
    old = {t["id"]: t for t in topics(load(), include_retired=True)}
    cats, seen = [], set()
    for c in tax.get("categories", []):
        name = " ".join(str(c.get("name", "")).split())[:60]
        if not name:
            raise ValueError("Every category needs a name.")
        if name.lower() in seen:
            raise ValueError(f"Two categories are named '{name}'.")
        seen.add(name.lower())
        cats.append({"name": name, "topics": []})
        for t in c.get("topics", []):
            tname = " ".join(str(t.get("name", "")).split())[:60]
            if not tname:
                raise ValueError(f"A topic in '{name}' has no name.")
            tid = t.get("id") or slug(tname)
            cats[-1]["topics"].append({"id": tid, "name": tname, "active": t.get("active", True) is not False})
    ids = [t["id"] for c in cats for t in c["topics"]]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError("Two topics would have the same name: " + ", ".join(sorted(dupes)))
    missing = set(old) - set(ids)
    if missing:  # keep removed topics as retired, so past items still have a label
        bucket = next((c for c in cats if c["name"] == "Other"), None) or cats[-1]
        bucket["topics"] += [{**old[i], "active": False} for i in sorted(missing)]
    if not any(t["active"] for c in cats for t in c["topics"]):
        raise ValueError("Keep at least one active topic.")
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({"categories": cats}, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"categories": cats}


def topics(tax: dict | None = None, include_retired: bool = False) -> list[dict]:
    tax = tax or load()
    return [{**t, "category": c["name"]} for c in tax["categories"] for t in c["topics"]
            if include_retired or t["active"]]


def lookup(topic_id: str | None) -> dict:
    """Topic id -> {id, name, category}. Unknown ids show as Uncategorized."""
    for t in topics(include_retired=True):
        if t["id"] == topic_id:
            return t
    return {"id": topic_id or "", "name": "Uncategorized", "category": "Uncategorized", "active": False}


def _picklist(active: list[dict]) -> str:
    out, last = [], None
    for t in active:
        if t["category"] != last:
            out.append(f"{t['category']}:")
            last = t["category"]
        out.append(f"  {t['id']}  ({t['name']})")
    return "\n".join(out)


SYSTEM = """You file items for reporting at Tallyline, a B2B SaaS for small professional-services firms
(time tracking, invoicing, client portal, payments, integrations). Pick the ONE topic id from the list below
that best describes what the item is mainly about. Use {fallback} only if nothing fits.

{picklist}

{instructions}"""


def assign(text: str, kind: str = "ticket", model: str = llm.DEFAULT_MODEL) -> str:
    """Suggest one topic id for a ticket or a survey comment."""
    active = topics()
    msgs = [{"role": "system", "content": SYSTEM.format(fallback=FALLBACK, picklist=_picklist(active),
                                                        instructions='Reply with JSON only: {"topic": "id"}')},
            {"role": "user", "content": f"{'Support ticket' if kind == 'ticket' else 'Survey comment'}:\n{text}"}]
    raw, _ = llm.chat_json(msgs, model)
    return _valid(raw.get("topic"), active)


def assign_many(texts: list[str], kind: str = "survey", model: str = llm.DEFAULT_MODEL) -> list[str]:
    """Suggest topics for several items in one call (used for survey runs)."""
    active = topics()
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    msgs = [{"role": "system", "content": SYSTEM.format(
                fallback=FALLBACK, picklist=_picklist(active),
                instructions=f'Reply with JSON only: {{"topics": ["id", ...]}} with exactly {len(texts)} ids, in order.')},
            {"role": "user", "content": f"{'Survey comments' if kind == 'survey' else 'Tickets'}:\n{numbered}"}]
    raw, _ = llm.chat_json(msgs, model)
    got = raw.get("topics") if isinstance(raw.get("topics"), list) else []
    if len(got) != len(texts):  # the model miscounted: fall back to one call each
        return [assign(t, kind, model) for t in texts]
    return [_valid(t, active) for t in got]


def _valid(topic_id, active: list[dict]) -> str:
    ids = {t["id"] for t in active}
    if topic_id in ids:
        return topic_id
    return FALLBACK if FALLBACK in ids else next(iter(ids))
