"""Score survey-comment tagging against the gold labels in data/surveys/, and check the summary's numbers.

Run:  python -m evals.voc_eval --label v1 [--group core|holdout|all]
Writes evals/results/<date_time>-voc-<label>-<group>.json (gitignored) and prints a summary.
"""
import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

from cxops import data, llm, voc
from cxops.ollama import ensure_running

RESULTS = Path(__file__).parent / "results"


def theme_scores(recs: list[dict]) -> dict:
    tp = sum(len(set(r["gold"]["themes"]) & set(r["pred"]["themes"])) for r in recs)
    fp = sum(len(set(r["pred"]["themes"]) - set(r["gold"]["themes"])) for r in recs)
    fn = sum(len(set(r["gold"]["themes"]) - set(r["pred"]["themes"])) for r in recs)
    p = tp / (tp + fp) if tp + fp else 0.0
    rcl = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": p, "recall": rcl, "f1": 2 * p * rcl / (p + rcl) if p + rcl else 0.0,
            "exact_match": sum(set(r["gold"]["themes"]) == set(r["pred"]["themes"]) for r in recs) / len(recs)}


def summarize(recs: list[dict]) -> dict:
    gold_f = [r for r in recs if r["gold"]["follow_up"]]
    pred_f = [r for r in recs if r["pred"]["follow_up"]]
    hit = sum(r["gold"]["follow_up"] and r["pred"]["follow_up"] for r in recs)
    return {
        "responses": len(recs),
        "themes": theme_scores(recs),
        "sentiment_accuracy": sum(r["gold"]["sentiment"] == r["pred"]["sentiment"] for r in recs) / len(recs),
        "follow_up_recall": hit / len(gold_f) if gold_f else 0.0,
        "follow_up_precision": hit / len(pred_f) if pred_f else 0.0,
        "follow_up_missed": [r["id"] for r in gold_f if not r["pred"]["follow_up"]],
        "follow_up_extra": [r["id"] for r in pred_f if not r["gold"]["follow_up"]],
        "median_seconds": statistics.median(r["seconds"] for r in recs),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--group", default="core", choices=["core", "holdout", "all"])
    ap.add_argument("--model", default=llm.DEFAULT_MODEL)
    a = ap.parse_args()
    responses = [r for r in data.surveys() if a.group == "all" or r["group"] == a.group]
    recs, tags = [], {}
    with ensure_running():
        for i, r in enumerate(responses, 1):
            t, secs = voc.tag(r, a.model)
            tags[r["id"]] = t
            recs.append({"id": r["id"], "score": r["score"], "comment": r["comment"], "seconds": round(secs, 2),
                         "gold": {k: r[k] for k in ("themes", "sentiment", "follow_up")},
                         "pred": {k: t[k] for k in ("themes", "sentiment", "follow_up")}, "reason": t["reason"]})
            print(f"\r{i}/{len(responses)} {r['id']}", end="", flush=True)
        stats = voc.compute_stats(responses, tags)
        summary, bad = voc.write_summary(stats, a.model)
    s = summarize(recs)
    s["summary_unsupported_numbers"] = bad
    th = s["themes"]
    print(f"\n\nResponses: {s['responses']}")
    print(f"Themes: precision {th['precision']:.1%}, recall {th['recall']:.1%}, F1 {th['f1']:.1%}, exact set {th['exact_match']:.1%}")
    print(f"Sentiment accuracy: {s['sentiment_accuracy']:.1%}")
    print(f"Follow-up: recall {s['follow_up_recall']:.1%} (missed {len(s['follow_up_missed'])}: {', '.join(s['follow_up_missed']) or '-'}), "
          f"precision {s['follow_up_precision']:.1%} (extra {len(s['follow_up_extra'])}: {', '.join(s['follow_up_extra']) or '-'})")
    print(f"Summary numbers not in the stats: {bad or 'none'}")
    print(f"Median {s['median_seconds']:.1f}s per comment\n\n{summary}")
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{datetime.now():%Y%m%d_%H%M%S}-voc-{a.label}-{a.group}.json"
    out.write_text(json.dumps({"label": a.label, "model": a.model, "summary": s, "llm_summary": summary,
                               "stats": stats, "records": recs}, indent=1), encoding="utf-8")
    print(f"\nSaved {out.relative_to(RESULTS.parent.parent)}")


if __name__ == "__main__":
    main()
