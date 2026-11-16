"""Load and validate the help-center articles, tickets, and survey responses."""
import tomllib
from functools import cache

from . import DATA

CATEGORIES = ["billing", "access", "bug", "how_to", "feature_request", "integration",
              "data_import", "cancellation", "spam"]
URGENCIES = ["urgent", "normal", "low"]
RESOLUTIONS = ["auto", "escalate", "spam"]
THEMES = ["onboarding", "billing_pricing", "support_speed", "bugs_reliability", "missing_feature",
          "integrations", "ease_of_use", "performance", "mobile", "praise_staff"]
SENTIMENTS = ["positive", "negative", "mixed", "neutral"]

# Assignment rules: category -> queue (code, not the model, decides the queue).
QUEUES = {
    "billing": "Billing", "access": "Tier 1", "how_to": "Tier 1",
    "bug": "Technical", "integration": "Technical", "data_import": "Technical",
    "feature_request": "Account Management", "cancellation": "Account Management",
    "spam": "Spam Review",
}


def _load_dir(folder: str, key: str, group_by_file: bool = True) -> list[dict]:
    items = []
    for path in sorted((DATA / folder).glob("*.toml")):
        for item in tomllib.loads(path.read_text(encoding="utf-8"))[key]:
            item.setdefault("group", "holdout" if path.stem.startswith("holdout") else "core")
            items.append(item)
    return items


@cache
def articles() -> dict[str, dict]:
    raw = tomllib.loads((DATA / "kb" / "articles.toml").read_text(encoding="utf-8"))["article"]
    return {a["id"]: {**a, "body": " ".join(a["body"].split())} for a in raw}


def tickets() -> list[dict]:
    return _load_dir("tickets", "ticket")


def surveys() -> list[dict]:
    return _load_dir("surveys", "responses")


def fact_found(fact: str, text: str) -> bool:
    """A required fact is 'a|b|c': any alternative appearing (case-insensitive) counts."""
    low = text.lower()
    return any(alt.strip().lower() in low for alt in fact.split("|"))


def validate() -> list[str]:
    problems, kb = [], articles()
    ids = set()
    for t in tickets():
        tid = t["id"]
        if tid in ids:
            problems.append(f"{tid}: duplicate id")
        ids.add(tid)
        for c in [t["category"]] + t.get("alt_category", []):
            if c not in CATEGORIES:
                problems.append(f"{tid}: bad category {c}")
        if t["urgency"] not in URGENCIES:
            problems.append(f"{tid}: bad urgency")
        if t["resolution"] not in RESOLUTIONS:
            problems.append(f"{tid}: bad resolution")
        if (t["category"] == "spam") != (t["resolution"] == "spam"):
            problems.append(f"{tid}: spam category and spam resolution must go together")
        if t["resolution"] == "auto":
            if t["urgency"] == "urgent" or t["category"] == "cancellation":
                problems.append(f"{tid}: urgent/cancellation tickets must escalate")
            a = kb.get(t.get("kb_id"))
            if not a:
                problems.append(f"{tid}: auto ticket needs a valid kb_id")
            elif not t.get("required_facts"):
                problems.append(f"{tid}: auto ticket needs required_facts")
            else:
                text = a["title"] + " " + a["body"]
                for f in t["required_facts"]:
                    if not fact_found(f, text):
                        problems.append(f"{tid}: fact '{f}' not in {a['id']}")
    sids = set()
    for s in surveys():
        if s["id"] in sids:
            problems.append(f"{s['id']}: duplicate id")
        sids.add(s["id"])
        if not 0 <= s["score"] <= 10:
            problems.append(f"{s['id']}: bad score")
        for th in s["themes"]:
            if th not in THEMES:
                problems.append(f"{s['id']}: bad theme {th}")
        if s["sentiment"] not in SENTIMENTS:
            problems.append(f"{s['id']}: bad sentiment")
    return problems


if __name__ == "__main__":
    probs = validate()
    t, s = tickets(), surveys()
    from collections import Counter
    print(f"{len(articles())} articles, {len(t)} tickets, {len(s)} survey responses")
    print("resolution:", dict(Counter(x["resolution"] for x in t)))
    print("category:", dict(Counter(x["category"] for x in t)))
    print("urgency:", dict(Counter(x["urgency"] for x in t)))
    print("follow_up:", dict(Counter(x["follow_up"] for x in s)), "sentiment:", dict(Counter(x["sentiment"] for x in s)))
    print("\n".join(probs) or "no problems")
