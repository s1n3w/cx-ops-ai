"""Voice of the customer: tag NPS survey comments, compute the numbers, write a leadership summary.

1. The model tags each comment: themes, sentiment, and whether someone should follow up.
2. Code computes every number (NPS by month and plan, themes by promoter/passive/detractor,
   the follow-up list). The model never does arithmetic.
3. The model writes a short summary from those numbers, and a check flags any number in the
   summary that isn't in the computed stats.

Run:  python -m cxops.voc [--group core] [--report out/voc-report.md]
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from . import ROOT, data, llm
from .data import SENTIMENTS, THEMES

THEME_HELP = """\
- onboarding: setup, getting started, moving data in during setup, training new people
- billing_pricing: money between the customer and Tallyline: price, value for money, plan cost, charges,
  seats, discounts, refunds, and payouts of client payments
- support_speed: experiences with the support team: how fast and how helpful (good or bad)
- bugs_reliability: errors, crashes, outages, lost or wrong data, things that break, security or privacy incidents
- missing_feature: asks for something the product doesn't have
- integrations: QuickBooks, Xero, Google/Outlook calendar, Zapier, the API, SSO (Okta, Entra), Stripe/online payments
- ease_of_use: everyday usability and workflow: easy, intuitive, saves time, or clunky and confusing
- performance: speed: fast, slow, laggy, timeouts
- mobile: the iOS/Android app
- praise_staff: praises a specific person or team at Tallyline"""

FOLLOW_UP_HELP = """\
follow_up = true when someone at Tallyline should contact this customer:
- a churn signal (cancelling, leaving at renewal, evaluating or moving to other tools, downgrading), or
- a problem they are still stuck on or waiting for us to fix, or
- a detractor (score 0-6) with a specific, fixable complaint.
Otherwise false. Vague complaints with nothing specific to fix ("too expensive", "terrible") are false
unless they also show a churn signal. Happy customers are false."""


def tag_messages(resp: dict) -> list[dict]:
    system = f"""You analyze NPS survey comments for Tallyline, a B2B SaaS for small professional-services firms
(time tracking, invoicing, client portal, payments, integrations).

Themes (tag every theme the comment actually talks about; none if it says nothing specific):
{THEME_HELP}

Sentiment: positive, negative, mixed (clearly both), or neutral (no opinion, e.g. "n/a", ".", "no comment").

{FOLLOW_UP_HELP}

Reply with JSON only: {{"themes": [], "sentiment": "...", "follow_up": false, "reason": "one short sentence"}}"""
    user = f"Score: {resp['score']}/10\nPlan: {resp['plan']}\nComment: {resp['comment']}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def normalize(raw: dict) -> dict:
    themes = sorted({t for t in (raw.get("themes") or []) if t in THEMES})
    sent = raw.get("sentiment") if raw.get("sentiment") in SENTIMENTS else "neutral"
    return {"themes": themes, "sentiment": sent, "follow_up": raw.get("follow_up") is True,
            "reason": str(raw.get("reason", ""))}


def tag(resp: dict, model: str = llm.DEFAULT_MODEL) -> tuple[dict, float]:
    raw, rep = llm.chat_json(tag_messages(resp), model)
    return normalize(raw), rep.seconds


def segment(score: int) -> str:
    return "promoter" if score >= 9 else "passive" if score >= 7 else "detractor"


def nps(scores: list[int]) -> int:
    if not scores:
        return 0
    return round(100 * (sum(s >= 9 for s in scores) - sum(s <= 6 for s in scores)) / len(scores))


def compute_stats(responses: list[dict], tags: dict[str, dict]) -> dict:
    by_month, by_plan = defaultdict(list), defaultdict(list)
    for r in responses:
        by_month[r["month"]].append(r["score"])
        by_plan[r["plan"]].append(r["score"])
    themes = {seg: Counter() for seg in ("promoter", "passive", "detractor")}
    for r in responses:
        themes[segment(r["score"])].update(tags[r["id"]]["themes"])
    follow = sorted((r for r in responses if tags[r["id"]]["follow_up"]), key=lambda r: (r["score"], r["id"]))
    seg_counts = Counter(segment(r["score"]) for r in responses)
    return {
        "responses": len(responses),
        "nps": nps([r["score"] for r in responses]),
        "promoters": seg_counts["promoter"], "passives": seg_counts["passive"], "detractors": seg_counts["detractor"],
        "nps_by_month": {m: {"nps": nps(s), "responses": len(s)} for m, s in sorted(by_month.items())},
        "nps_by_plan": {p: {"nps": nps(s), "responses": len(s)} for p, s in sorted(by_plan.items())},
        "detractor_themes": themes["detractor"].most_common(),
        "promoter_themes": themes["promoter"].most_common(),
        "follow_up_count": len(follow),
        "follow_up": [{"id": r["id"], "score": r["score"], "plan": r["plan"], "comment": r["comment"],
                       "why": tags[r["id"]]["reason"]} for r in follow],
    }


def summary_messages(stats: dict) -> list[dict]:
    facts = {k: v for k, v in stats.items() if k != "follow_up"}
    facts["follow_up_examples"] = [f["comment"] for f in stats["follow_up"][:8]]
    system = """You write a monthly voice-of-the-customer summary for Tallyline's leadership team.
Use ONLY the numbers in the data below; do not calculate new numbers (no differences, averages, or percentages
that aren't given). Write about 200 words of plain Markdown with three short sections:
**Headline** (overall NPS and the trend by month), **What's driving detractors** (top themes with counts and
one or two example problems), and **Recommended actions** (3 bullets, specific and practical)."""
    return [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(facts, indent=1)}]


def unsupported_numbers(summary: str, stats: dict) -> list[str]:
    """Numbers in the summary that don't appear anywhere in the computed stats."""
    allowed = set(re.findall(r"-?\d+(?:\.\d+)?", json.dumps({k: v for k, v in stats.items() if k != "follow_up"})))
    allowed |= {"1", "2", "3"}  # list numbering / "3 bullets"
    found = re.findall(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?", summary)
    return [n for n in found if n.replace(",", "").lstrip("+") not in allowed]


def write_summary(stats: dict, model: str = llm.DEFAULT_MODEL) -> tuple[str, list[str]]:
    text = llm.chat(summary_messages(stats), model).text.strip()
    return text, unsupported_numbers(text, stats)


def report_markdown(stats: dict, summary: str, bad_numbers: list[str]) -> str:
    lines = [f"# Voice of the Customer report ({date.today():%B %d, %Y})", "",
             f"{stats['responses']} responses. NPS **{stats['nps']}** "
             f"({stats['promoters']} promoters, {stats['passives']} passives, {stats['detractors']} detractors).", "",
             "## Summary", "", summary, ""]
    if bad_numbers:
        lines += [f"> Check: these numbers in the summary aren't in the computed stats: {', '.join(bad_numbers)}", ""]
    lines += ["## NPS by month", "", "| Month | NPS | Responses |", "|---|---|---|"]
    lines += [f"| {m} | {v['nps']} | {v['responses']} |" for m, v in stats["nps_by_month"].items()]
    lines += ["", "## NPS by plan", "", "| Plan | NPS | Responses |", "|---|---|---|"]
    lines += [f"| {p} | {v['nps']} | {v['responses']} |" for p, v in stats["nps_by_plan"].items()]
    lines += ["", "## Themes among detractors", "", "| Theme | Mentions |", "|---|---|"]
    lines += [f"| {t} | {n} |" for t, n in stats["detractor_themes"]]
    lines += ["", f"## Follow up with these {stats['follow_up_count']} customers (lowest score first)", "",
              "| ID | Score | Plan | Comment | Why |", "|---|---|---|---|---|"]
    lines += [f"| {f['id']} | {f['score']} | {f['plan']} | {f['comment']} | {f['why']} |" for f in stats["follow_up"]]
    return "\n".join(lines) + "\n"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Analyze NPS survey comments.")
    ap.add_argument("--group", default="core", choices=["core", "holdout", "all"])
    ap.add_argument("--report", default=str(ROOT / "out" / "voc-report.md"))
    a = ap.parse_args()
    responses = [r for r in data.surveys() if a.group == "all" or r["group"] == a.group]
    from .ollama import ensure_running
    with ensure_running():
        tags = {}
        for i, r in enumerate(responses, 1):
            tags[r["id"]], _ = tag(r)
            print(f"\rTagged {i}/{len(responses)}", end="", flush=True)
        stats = compute_stats(responses, tags)
        summary, bad = write_summary(stats)
    out = Path(a.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report_markdown(stats, summary, bad), encoding="utf-8")
    print(f"\n\n{summary}\n\nReport saved to {out}")


if __name__ == "__main__":
    main()
