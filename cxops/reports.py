"""Custom reports over the local history, and Excel export.

A report spec:
  {"kind": "ticket" | "response",
   "filters": {"from": "2026-11-01", "to": "2026-11-30", "<field>": [allowed values], ...},
   "group_by": "<field>", "split_by": "<field>" or "", "chart": "count" | "nps" | "auto_rate" | ...,
   "name": "..."}
"""
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from . import history, taxonomy

DEMO_NOTE = ("Demo data, not real customers: Tallyline is a fictional company made up for this project. Its help "
             "center, support tickets, and survey responses are all invented for testing.")
SAVED = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "cx-ops-ai" / "reports.json"
EXPORT_DIR = Path.home() / "Documents" / "CX Ops AI exports"

LABELS = {
    "category": "Category", "topic": "Topic", "type": "Type", "queue": "Queue", "decision": "Decision",
    "urgency": "Urgency", "plan": "Plan", "source": "Source", "day": "Day", "week": "Week of", "month": "Month",
    "topic_by": "Topic set by", "segment": "NPS segment", "sentiment": "Sentiment", "follow_up": "Follow-up",
    "theme": "Theme", "score": "Score",
}
GROUPS = {
    "ticket": ["category", "topic", "type", "queue", "decision", "urgency", "plan", "day", "week", "month", "source", "topic_by"],
    "response": ["category", "topic", "segment", "sentiment", "follow_up", "plan", "month", "theme", "score", "source", "topic_by"],
}
FILTERS = {
    "ticket": ["category", "topic", "type", "queue", "decision", "urgency", "plan", "source", "topic_by"],
    "response": ["category", "topic", "segment", "sentiment", "follow_up", "plan", "source", "topic_by"],
}
CHARTS = {"ticket": ["count", "auto_rate", "escalated", "urgent"],
          "response": ["count", "nps", "avg_score", "follow_ups"]}
METRIC_LABELS = {"count": "Count", "share": "% of total", "auto_rate": "Auto-resolved %", "escalated": "Sent to a person",
                 "urgent": "Urgent", "nps": "NPS", "avg_score": "Avg score", "follow_ups": "Follow-ups"}
DISPLAY = {"decision": {"auto": "Auto-resolved", "escalate": "Sent to a person", "spam": "Spam"},
           "type": {"how_to": "How-to", "feature_request": "Feature request", "data_import": "Import / export"},
           "topic_by": {"ai": "AI", "you": "You"}, "source": {"typed": "Typed", "test": "Test set", "survey run": "Survey run"}}

STARTERS = [
    {"id": "starter-1", "name": "Ticket volume by category", "starter": True,
     "spec": {"kind": "ticket", "filters": {}, "group_by": "category", "split_by": "", "chart": "count"}},
    {"id": "starter-2", "name": "Ticket topics by decision", "starter": True,
     "spec": {"kind": "ticket", "filters": {}, "group_by": "topic", "split_by": "decision", "chart": "count"}},
    {"id": "starter-3", "name": "Auto-resolution rate by category", "starter": True,
     "spec": {"kind": "ticket", "filters": {}, "group_by": "category", "split_by": "", "chart": "auto_rate"}},
    {"id": "starter-4", "name": "NPS by category", "starter": True,
     "spec": {"kind": "response", "filters": {}, "group_by": "category", "split_by": "", "chart": "nps"}},
    {"id": "starter-5", "name": "What detractors talk about", "starter": True,
     "spec": {"kind": "response", "filters": {"segment": ["detractor"]}, "group_by": "topic", "split_by": "", "chart": "count"}},
    {"id": "starter-6", "name": "Follow-ups by plan and category", "starter": True,
     "spec": {"kind": "response", "filters": {"follow_up": ["Yes"]}, "group_by": "plan", "split_by": "category", "chart": "count"}},
]


# ---------------------------------------------------------------- rows
def _week(d: str) -> str:
    day = date.fromisoformat(d[:10])
    return (day - timedelta(days=day.weekday())).isoformat()


def enriched(kind: str) -> list[dict]:
    """History rows with the reporting fields filled in (category/topic names, date buckets, readable values)."""
    out = []
    for r in history.rows(kind):
        t = taxonomy.lookup(r.get("topic_id"))
        r = {**r, "topic": t["name"], "category": t["category"]}
        if kind == "ticket":
            r["day"], r["week"], r["month"] = r["created"][:10], _week(r["created"]), r["created"][:7]
            r["date"] = r["created"][:10]
        else:
            r["month"] = r.get("month") or r["created"][:7]
            r["date"] = r["month"] + "-01"
            r["follow_up"] = "Yes" if r["follow_up"] else "No"
            r["score"] = int(r["score"])
        for field, names in DISPLAY.items():
            if field in r and r[field] in names:
                r[field] = names[r[field]]
        out.append(r)
    return out


def _passes(r: dict, filters: dict) -> bool:
    # Tickets filter by the day they were triaged; survey responses by the month they were given.
    by_day = "day" in r
    key = r["day"] if by_day else r["month"]
    lo, hi = filters.get("from") or "", filters.get("to") or ""
    if lo and key < (lo if by_day else lo[:7]):
        return False
    if hi and key > (hi if by_day else hi[:7]):
        return False
    for field, allowed in filters.items():
        if field in ("from", "to") or not allowed:
            continue
        values = r.get(field)
        values = values if isinstance(values, list) else [values]
        if not any(str(v) in [str(a) for a in allowed] for v in values):
            return False
    return True


def filtered(spec: dict) -> list[dict]:
    return [r for r in enriched(spec["kind"]) if _passes(r, spec.get("filters") or {})]


# ---------------------------------------------------------------- metrics
def _metrics(kind: str, rs: list[dict], total: int) -> dict:
    m = {"count": len(rs), "share": round(100 * len(rs) / total, 1) if total else 0.0}
    if kind == "ticket":
        real = [r for r in rs if r["decision"] != "Spam"]
        m["auto_rate"] = round(100 * sum(r["decision"] == "Auto-resolved" for r in real) / len(real), 1) if real else 0.0
        m["escalated"] = sum(r["decision"] == "Sent to a person" for r in rs)
        m["urgent"] = sum(r["urgency"] == "urgent" for r in rs)
    else:
        scores = [r["score"] for r in rs]
        m["nps"] = round(100 * (sum(s >= 9 for s in scores) - sum(s <= 6 for s in scores)) / len(scores)) if scores else 0
        m["avg_score"] = round(sum(scores) / len(scores), 1) if scores else 0.0
        m["follow_ups"] = sum(r["follow_up"] == "Yes" for r in rs)
    return m


def _keys(r: dict, field: str) -> list:
    v = r.get("themes") if field == "theme" else r.get(field)
    if field == "theme":
        return v or ["(none)"]
    return [v if v not in (None, "") else "(blank)"]


def _order(field: str, keys) -> list:
    if field in ("day", "week", "month", "score"):
        return sorted(keys)
    if field == "category":
        order = [c["name"] for c in taxonomy.load()["categories"]] + ["Uncategorized"]
        return sorted(keys, key=lambda k: order.index(k) if k in order else 999)
    return list(keys)  # caller sorts by count


def run(spec: dict) -> dict:
    kind, gb, sb = spec["kind"], spec.get("group_by") or "category", spec.get("split_by") or ""
    rs = filtered(spec)
    groups = defaultdict(list)
    for r in rs:
        for k in _keys(r, gb):
            groups[k].append(r)
    keys = _order(gb, groups)
    if gb not in ("day", "week", "month", "score", "category"):
        keys = sorted(keys, key=lambda k: -len(groups[k]))
    table = [{"group": str(k), **_metrics(kind, groups[k], len(rs))} for k in keys]
    split = None
    if sb:
        cols = Counter(k for r in rs for k in _keys(r, sb))
        col_keys = _order(sb, cols) if sb in ("day", "week", "month", "score", "category") else [k for k, _ in cols.most_common()]
        split = {"field": sb, "label": LABELS[sb], "columns": [str(c) for c in col_keys],
                 "cells": {str(k): {str(c): sum(c in _keys(r, sb) for r in groups[k]) for c in col_keys} for k in keys}}
    return {"kind": kind, "group_label": LABELS[gb], "rows": len(rs), "table": table, "split": split,
            "totals": _metrics(kind, rs, len(rs)), "metric_labels": METRIC_LABELS,
            "metrics": ["count", "share"] + (["auto_rate", "escalated", "urgent"] if kind == "ticket" else ["nps", "avg_score", "follow_ups"])}


def options() -> dict:
    """What the report builder can offer: fields, and the values present in history for each filter."""
    out = {"labels": LABELS, "groups": GROUPS, "filters": FILTERS, "charts": CHARTS, "metric_labels": METRIC_LABELS,
           "values": {}, "counts": history.counts()}
    for kind in ("ticket", "response"):
        rs = enriched(kind)
        vals = {}
        for f in FILTERS[kind]:
            seen = Counter(v for r in rs for v in _keys(r, f) if v != "(blank)")
            if f == "category":
                vals[f] = _order("category", set(seen) | {c["name"] for c in taxonomy.load()["categories"]})
            elif f == "topic":
                vals[f] = sorted(set(seen) | {t["name"] for t in taxonomy.topics()})
            else:
                vals[f] = sorted(seen)
        out["values"][kind] = vals
    return out


# ---------------------------------------------------------------- saved reports
def saved() -> list[dict]:
    try:
        mine = json.loads(SAVED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        mine = []
    return STARTERS + mine


def save_report(name: str, spec: dict, report_id: str | None = None) -> dict:
    name = " ".join(name.split())[:80]
    if not name:
        raise ValueError("Give the report a name.")
    mine = [r for r in saved() if not r.get("starter")]
    if report_id and any(r["id"] == report_id for r in mine):
        for r in mine:
            if r["id"] == report_id:
                r.update(name=name, spec=spec)
                item = r
    else:
        item = {"id": f"r{datetime.now():%Y%m%d%H%M%S%f}", "name": name, "spec": spec}
        mine.append(item)
    SAVED.parent.mkdir(parents=True, exist_ok=True)
    SAVED.write_text(json.dumps(mine, indent=1, ensure_ascii=False), encoding="utf-8")
    return item


def delete_report(report_id: str) -> None:
    mine = [r for r in saved() if not r.get("starter") and r["id"] != report_id]
    SAVED.write_text(json.dumps(mine, indent=1, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- Excel
TICKET_COLS = [("created", "Created"), ("source", "Source"), ("test_id", "Test ID"), ("plan", "Plan"),
               ("category", "Category"), ("topic", "Topic"), ("topic_by", "Topic set by"), ("type", "Type"),
               ("urgency", "Urgency"), ("queue", "Queue"), ("decision", "Decision"), ("risk_flags", "Risk flags"),
               ("subject", "Subject"), ("body", "Message"), ("kb_id", "Article used"), ("reply", "Drafted reply"),
               ("why", "Reason"), ("seconds", "Seconds")]
RESPONSE_COLS = [("month", "Month"), ("source", "Source"), ("response_id", "Response ID"), ("plan", "Plan"),
                 ("score", "Score"), ("segment", "NPS segment"), ("category", "Category"), ("topic", "Topic"),
                 ("topic_by", "Topic set by"), ("sentiment", "Sentiment"), ("themes", "Themes"),
                 ("follow_up", "Follow-up"), ("reason", "Why flagged"), ("comment", "Comment"), ("created", "Analyzed")]


def export_xlsx(spec: dict, name: str = "") -> Path:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.chart.legend import Legend
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    rep, rs = run(spec), filtered(spec)
    kind = spec["kind"]
    title = name or f"{'Tickets' if kind == 'ticket' else 'Survey responses'} by {rep['group_label'].lower()}"
    wb = Workbook()
    head = PatternFill("solid", fgColor="3D2618")
    white = Font(bold=True, color="FFFFFF")

    ws = wb.active
    ws.title = "Report"
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=16)
    ws["A2"] = f"CX Ops AI · exported {datetime.now():%B %d, %Y %I:%M %p} · {rep['rows']} {'tickets' if kind == 'ticket' else 'responses'}"
    ws["A3"] = "Filters: " + (_describe_filters(spec.get("filters") or {}) or "none")
    for c in ("A2", "A3"):
        ws[c].font = Font(italic=True, color="666666")
    ws["A4"] = DEMO_NOTE
    ws["A4"].font = Font(bold=True, color="B5541C")
    start = 6
    if rep["split"]:
        cols = [rep["group_label"]] + rep["split"]["columns"] + ["Total"]
        ws.cell(start, 1, f"Count by {rep['group_label'].lower()} and {rep['split']['label'].lower()}").font = Font(bold=True)
        start += 1
        for j, v in enumerate(cols, start=1):
            ws.cell(start, j, v)
        for i, row in enumerate(rep["table"], start=1):
            cells = rep["split"]["cells"][row["group"]]
            vals = [row["group"]] + [cells[c] for c in rep["split"]["columns"]] + [row["count"]]
            for j, v in enumerate(vals):
                ws.cell(start + i, j + 1, v)
        metric_cols = cols
    else:
        metric_cols = [rep["group_label"]] + [METRIC_LABELS[m] for m in rep["metrics"]]
        for j, v in enumerate(metric_cols):
            ws.cell(start, j + 1, v)
        for i, row in enumerate(rep["table"], start=1):
            ws.cell(start + i, 1, row["group"])
            for j, m in enumerate(rep["metrics"], start=2):
                ws.cell(start + i, j, row[m])
        tot = len(rep["table"]) + start + 1
        ws.cell(tot, 1, "Total").font = Font(bold=True)
        for j, m in enumerate(rep["metrics"], start=2):
            ws.cell(tot, j, rep["totals"][m]).font = Font(bold=True)
    for j in range(1, len(metric_cols) + 1):
        c = ws.cell(start, j)
        c.fill, c.font, c.alignment = head, white, Alignment(horizontal="center" if j > 1 else "left")
    ws.column_dimensions["A"].width = 32
    for j in range(2, len(metric_cols) + 1):
        ws.column_dimensions[get_column_letter(j)].width = 16
    if rep["table"]:
        chart_metric = spec.get("chart") or "count"
        col = 2 + rep["metrics"].index(chart_metric) if not rep["split"] and chart_metric in rep["metrics"] else 2
        ch = BarChart()
        ch.type, ch.style, ch.legend = "bar", 10, None
        ch.title = (METRIC_LABELS.get(chart_metric, "Count") if not rep["split"] else "Count") + f" by {rep['group_label'].lower()}"
        n = len(rep["table"])
        if rep["split"]:
            last = len(metric_cols) - 1
            ch.grouping, ch.overlap, ch.legend = "stacked", 100, Legend()
            ch.add_data(Reference(ws, min_col=2, max_col=last, min_row=start, max_row=start + n), titles_from_data=True)
        else:
            ch.add_data(Reference(ws, min_col=col, max_col=col, min_row=start, max_row=start + n), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=start + 1, max_row=start + n))
        ch.y_axis.majorGridlines = None
        ch.x_axis.delete = ch.y_axis.delete = False      # openpyxl 3.1 hides axes unless told otherwise
        ch.x_axis.scaling.orientation = "maxMin"         # bars top-to-bottom in the same order as the table
        ch.y_axis.crosses = "max"                        # ...which would put the value axis on top; keep it at the bottom
        if rep["split"] or chart_metric in ("count", "escalated", "urgent", "follow_ups"):
            biggest = max(row["count"] if rep["split"] else row[chart_metric] for row in rep["table"])
            ch.y_axis.majorUnit = max(1, round(biggest / 5))  # whole items, no 0.5 steps
            ch.y_axis.number_format = "0"
        ch.height, ch.width = max(7, 0.6 * n + 3), 18
        ws.add_chart(ch, f"A{start + n + 3}")  # below the table, so it prints on the same page

    data = wb.create_sheet("Data")
    cols = TICKET_COLS if kind == "ticket" else RESPONSE_COLS
    data.append([label for _, label in cols])
    for r in rs:
        data.append([", ".join(r[k]) if isinstance(r.get(k), list) else r.get(k) for k, _ in cols])
    if rs:
        tab = Table(displayName="Data", ref=f"A1:{get_column_letter(len(cols))}{len(rs) + 1}")
        tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        data.add_table(tab)
    widths = {"Message": 60, "Drafted reply": 60, "Comment": 60, "Subject": 34, "Reason": 40, "Why flagged": 40}
    for j, (_, label) in enumerate(cols, start=1):
        data.column_dimensions[get_column_letter(j)].width = widths.get(label, 16)
    data.freeze_panes = "A2"

    about = wb.create_sheet("About")
    for line in [("Report", title), ("Exported", datetime.now().strftime("%Y-%m-%d %H:%M")),
                 ("Rows", rep["rows"]), ("Group by", rep["group_label"]),
                 ("Split by", rep["split"]["label"] if rep["split"] else "-"),
                 ("Filters", _describe_filters(spec.get("filters") or {}) or "none"),
                 ("Demo data", DEMO_NOTE),
                 ("Note", "Category and Topic come from CX Ops AI's picklist. 'Topic set by' says whether the AI suggested "
                          "it or a person chose it. All data stays on this PC.")]:
        about.append(line)
    about.column_dimensions["A"].width, about.column_dimensions["B"].width = 14, 100

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\- ]+", "", title).strip()[:60] or "report"
    path = EXPORT_DIR / f"{safe} {datetime.now():%Y-%m-%d %H%M%S}.xlsx"
    wb.save(path)
    return path


def _describe_filters(f: dict) -> str:
    parts = []
    if f.get("from") or f.get("to"):
        parts.append(f"dates {f.get('from') or 'start'} to {f.get('to') or 'today'}")
    for k, v in f.items():
        if k not in ("from", "to") and v:
            parts.append(f"{LABELS.get(k, k)}: {', '.join(map(str, v))}")
    return "; ".join(parts)
