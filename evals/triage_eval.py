"""Score ticket triage against the gold labels in data/tickets/.

Run:  python -m evals.triage_eval --label v1 [--ids t001,t002] [--group core|holdout|all]
Writes evals/results/<date_time>-triage-<label>.json (gitignored) and prints a summary.
"""
import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from cxops import data, llm
from cxops.ollama import ensure_running
from cxops.triage import triage

RESULTS = Path(__file__).parent / "results"


def grade(t: dict, r) -> dict:
    """Compare one prediction with its gold labels."""
    rec = {
        "id": t["id"], "group": t["group"],
        "gold": {k: t.get(k) for k in ("category", "urgency", "resolution", "kb_id")},
        "pred": {"category": r.category, "urgency": r.urgency, "resolution": r.resolution, "kb_id": r.kb_id,
                 "risk_flags": r.risk_flags},
        "why": r.why, "reply": r.reply, "seconds": round(r.seconds, 2), "tokens": r.tokens,
        "category_ok": r.category in [t["category"]] + t.get("alt_category", []),
        "urgency_ok": r.urgency == t["urgency"],
        "resolution_ok": r.resolution == t["resolution"],
    }
    if r.resolution == "auto":
        if t["resolution"] == "auto":
            missing = [f for f in t["required_facts"] if not data.fact_found(f, r.reply)]
            rec["missing_facts"] = missing
            rec["answer"] = "correct" if not missing else "incomplete"
        else:
            rec["answer"] = "unsafe"   # answered a ticket a person had to handle (or replied to spam)
    return rec


def summarize(recs: list[dict]) -> dict:
    n = len(recs)
    pct = lambda k, xs=recs: sum(x[k] for x in xs) / len(xs) if xs else 0.0
    real = [x for x in recs if x["gold"]["resolution"] != "spam"]
    autos = [x for x in recs if x["pred"]["resolution"] == "auto"]
    answers = Counter(x.get("answer") for x in autos)
    gold_auto = [x for x in recs if x["gold"]["resolution"] == "auto"]
    gold_spam = [x for x in recs if x["gold"]["resolution"] == "spam"]
    pred_spam = [x for x in recs if x["pred"]["resolution"] == "spam"]
    secs = sorted(x["seconds"] for x in recs)
    s = {
        "tickets": n,
        "category_accuracy": pct("category_ok"),
        "urgency_accuracy": pct("urgency_ok"),
        "decision_accuracy": pct("resolution_ok"),
        "auto_resolved": len(autos), "real_tickets": len(real),
        "auto_resolution_rate": len([x for x in autos if x["gold"]["resolution"] != "spam"]) / len(real) if real else 0,
        "auto_correct": answers["correct"], "auto_incomplete": answers["incomplete"], "auto_unsafe": answers["unsafe"],
        "auto_answer_accuracy": answers["correct"] / len(autos) if autos else 0.0,
        "answerable_resolved_correctly": sum(x.get("answer") == "correct" for x in gold_auto) / len(gold_auto) if gold_auto else 0,
        "kb_match_on_auto": sum(x["pred"]["kb_id"] == x["gold"]["kb_id"] for x in autos if x["gold"]["resolution"] == "auto"),
        "spam_caught": sum(x["pred"]["resolution"] == "spam" for x in gold_spam), "spam_total": len(gold_spam),
        "false_spam": sum(x["gold"]["resolution"] != "spam" for x in pred_spam),
        "urgent_caught": sum(x["pred"]["urgency"] == "urgent" for x in recs if x["gold"]["urgency"] == "urgent"),
        "urgent_total": sum(x["gold"]["urgency"] == "urgent" for x in recs),
        "false_urgent": sum(x["pred"]["urgency"] == "urgent" and x["gold"]["urgency"] != "urgent" for x in recs),
        "urgent_sent_to_person": sum(x["pred"]["resolution"] == "escalate" for x in recs if x["gold"]["urgency"] == "urgent"),
        "median_seconds": statistics.median(secs) if secs else 0, "p90_seconds": secs[int(0.9 * (n - 1))] if secs else 0,
    }
    return s


def print_summary(s: dict, recs: list[dict]) -> None:
    p = lambda v: f"{100 * v:.1f}%"
    print(f"\nTickets: {s['tickets']}")
    print(f"Category accuracy:   {p(s['category_accuracy'])}")
    print(f"Urgency accuracy:    {p(s['urgency_accuracy'])}  (low vs normal is a judgment call; urgent is what matters)")
    print(f"Urgent caught:       {s['urgent_caught']}/{s['urgent_total']}, false alarms {s['false_urgent']}, "
          f"urgent tickets sent to a person {s['urgent_sent_to_person']}/{s['urgent_total']}")
    print(f"Decision accuracy:   {p(s['decision_accuracy'])}  (auto / escalate / spam)")
    print(f"Auto-resolved:       {s['auto_resolved']} of {s['real_tickets']} real tickets ({p(s['auto_resolution_rate'])})")
    print(f"  correct answers:   {s['auto_correct']}  ({p(s['auto_answer_accuracy'])} of auto replies)")
    print(f"  incomplete:        {s['auto_incomplete']}")
    print(f"  UNSAFE (should have gone to a person): {s['auto_unsafe']}")
    print(f"Answerable tickets resolved correctly: {p(s['answerable_resolved_correctly'])}")
    print(f"Spam caught: {s['spam_caught']}/{s['spam_total']}, real tickets marked spam: {s['false_spam']}")
    print(f"Latency: median {s['median_seconds']:.1f}s, p90 {s['p90_seconds']:.1f}s")
    misses = [x for x in recs if not (x["category_ok"] and x["urgency_ok"] and x["resolution_ok"]) or x.get("answer") in ("incomplete", "unsafe")]
    if misses:
        print("\nMisses:")
        for x in misses:
            bits = []
            if not x["category_ok"]:
                bits.append(f"category {x['pred']['category']} (gold {x['gold']['category']})")
            if not x["urgency_ok"]:
                bits.append(f"urgency {x['pred']['urgency']} (gold {x['gold']['urgency']})")
            if not x["resolution_ok"]:
                bits.append(f"decision {x['pred']['resolution']} (gold {x['gold']['resolution']}): {x['why']}")
            if x.get("answer") == "incomplete":
                bits.append(f"reply missing {x['missing_facts']}")
            print(f"  {x['id']}: " + "; ".join(bits))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--ids")
    ap.add_argument("--group", default="core", choices=["core", "holdout", "all"])
    ap.add_argument("--model", default=llm.DEFAULT_MODEL)
    a = ap.parse_args()
    tickets = data.tickets()
    if a.ids:
        want = set(a.ids.split(","))
        tickets = [t for t in tickets if t["id"] in want]
    elif a.group != "all":
        tickets = [t for t in tickets if t["group"] == a.group]
    recs = []
    with ensure_running():
        for i, t in enumerate(tickets, 1):
            r = triage(t, a.model)
            recs.append(grade(t, r))
            print(f"\r{i}/{len(tickets)} {t['id']}", end="", flush=True)
    s = summarize(recs)
    print_summary(s, recs)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{datetime.now():%Y%m%d_%H%M%S}-triage-{a.label}{'-subset' if a.ids else ''}-{a.group}.json"
    out.write_text(json.dumps({"label": a.label, "model": a.model, "summary": s, "records": recs}, indent=1), encoding="utf-8")
    print(f"\nSaved {out.relative_to(RESULTS.parent.parent)}")


if __name__ == "__main__":
    main()
