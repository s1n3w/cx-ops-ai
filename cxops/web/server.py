"""Local HTTP server for the desktop UI: static files plus a small JSON API.

Endpoints
  GET  /api/status                 model readiness and data counts
  POST /api/triage   {plan, subject, body}       one ticket through the triage pipeline
  GET  /api/sample?kind=any|auto|escalate|spam   a random test ticket with its correct answer
  POST /api/comment  {score, plan, comment}      tag one survey comment
  POST /api/survey   {group: holdout|core}       start the survey report in the background
  GET  /api/survey                               progress, then the finished report
  GET  /api/articles                             the help center (built-in + your own) and the test tickets each answers
  POST /api/articles {id?, title, body}          add or update one of your own articles
  DELETE /api/articles/<id>                      delete one of your own articles
  GET  /api/taxonomy · POST /api/taxonomy        the Category > Topic picklist (read / save edits)
  POST /api/topic    {kind, id, topic_id}        a person overrides an item's topic
  GET  /api/report-options                       fields and values for the report builder
  POST /api/report   {spec}                      run a report over the local history
  GET  /api/reports · POST /api/reports · DELETE /api/reports/<id>   saved reports
  POST /api/export   {spec, name}                write an .xlsx to Documents\\CX Ops AI exports
  POST /api/open     {path, folder}              open an exported file, or its folder
  POST /api/history/clear {kind}                 clear saved tickets and/or responses
"""
import json
import mimetypes
import random
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import os
from datetime import datetime

from .. import data, history, reports, taxonomy, triage, voc
from ..data import QUEUES

STATIC = Path(__file__).with_name("static")
_model = threading.Lock()  # one local model: requests take turns


class AppState:
    model_ready = False
    model_error: str | None = None
    survey = {"state": "idle"}


def suggest_topic(text: str, kind: str) -> str:
    """The reporting topic is a separate, best-effort step: if it fails, the item is still saved."""
    try:
        with _model:
            return taxonomy.assign(text, kind)
    except Exception:
        traceback.print_exc()
        return taxonomy.FALLBACK


def topic_info(topic_id: str, by: str = "ai") -> dict:
    t = taxonomy.lookup(topic_id)
    return {"id": t["id"], "name": t["name"], "category": t["category"], "by": by}


def do_triage(ticket: dict, test_id: str = "") -> dict:
    with _model:
        t = triage.triage(ticket)
    topic_id = suggest_topic(f"Subject: {ticket.get('subject', '')}\n{ticket['body']}", "ticket")
    hid = history.add_ticket({
        "source": "test" if test_id else "typed", "test_id": test_id or None, "plan": ticket["plan"],
        "subject": ticket.get("subject", ""), "body": ticket["body"], "type": t.category, "urgency": t.urgency,
        "queue": t.queue, "decision": t.resolution, "risk_flags": t.risk_flags, "kb_id": t.kb_id, "reply": t.reply,
        "why": t.why, "seconds": round(t.seconds, 1), "topic_id": topic_id, "topic_by": "ai"})
    article = data.articles().get(t.kb_id) if t.kb_id else None
    return {
        "history_id": hid, "topic": topic_info(topic_id),
        "category": t.category, "urgency": t.urgency, "queue": t.queue, "resolution": t.resolution,
        "risk_flags": t.risk_flags, "reply": t.reply, "why": t.why, "seconds": round(t.seconds, 1),
        "article": {"id": article["id"], "title": article["title"], "body": article["body"],
                    "custom": bool(article.get("custom"))} if article else None,
    }


def sample(kind: str, ticket_id: str = "") -> dict:
    tickets = data.tickets()
    by_id = [t for t in tickets if t["id"] == ticket_id]
    t = by_id[0] if by_id else random.choice([t for t in tickets if kind in ("any", "") or t["resolution"] == kind])
    return {"id": t["id"], "plan": t["plan"], "subject": t["subject"], "body": t["body"],
            "gold": {"category": t["category"], "alt_category": t.get("alt_category", []), "urgency": t["urgency"],
                     "resolution": t["resolution"], "queue": QUEUES[t["category"]], "note": t.get("note", "")}}


def clean_spec(spec: dict) -> dict:
    """Only allow known fields into a report spec."""
    kind = "response" if spec.get("kind") == "response" else "ticket"
    gb = spec.get("group_by") if spec.get("group_by") in reports.GROUPS[kind] else "category"
    sb = spec.get("split_by") if spec.get("split_by") in reports.GROUPS[kind] and spec.get("split_by") != gb else ""
    chart = spec.get("chart") if spec.get("chart") in reports.CHARTS[kind] else "count"
    f = spec.get("filters") or {}
    filters = {k: [str(v) for v in f[k]][:100] for k in reports.FILTERS[kind] if isinstance(f.get(k), list) and f[k]}
    for k in ("from", "to"):
        if isinstance(f.get(k), str) and len(f[k]) in (7, 10):
            filters[k] = f[k]
    return {"kind": kind, "group_by": gb, "split_by": sb, "chart": chart, "filters": filters}


def list_articles() -> dict:
    answers = {}
    for t in data.tickets():
        if t.get("kb_id"):
            answers.setdefault(t["kb_id"], []).append({"id": t["id"], "subject": t["subject"]})
    out = [{**a, "custom": False, "tickets": answers.get(a["id"], [])} for a in data.base_articles().values()]
    out += [{**a, "tickets": []} for a in data.custom_articles().values()]
    return {"articles": out, "max_custom": data.MAX_CUSTOM, "max_body": data.MAX_CUSTOM_BODY,
            "custom_file": str(data.CUSTOM_FILE)}


def run_survey(group: str) -> None:
    s = AppState.survey
    try:
        responses = [r for r in data.surveys() if r["group"] == group]
        s.update(state="running", done=0, total=len(responses), step="Tagging comments")
        tags = {}
        for r in responses:
            with _model:
                tags[r["id"]], _ = voc.tag(r)
            s["done"] += 1
        s.update(step="Filing comments by topic", done=0)
        topics = {}
        for i in range(0, len(responses), 10):
            chunk = responses[i:i + 10]
            try:
                with _model:
                    ids = taxonomy.assign_many([r["comment"] for r in chunk], "survey")
            except Exception:
                traceback.print_exc()
                ids = [taxonomy.FALLBACK] * len(chunk)
            topics.update({r["id"]: tid for r, tid in zip(chunk, ids)})
            s["done"] += len(chunk)
        for r in responses:
            t = tags[r["id"]]
            history.add_response({
                "source": "survey run", "response_id": r["id"], "month": r["month"], "plan": r["plan"],
                "score": r["score"], "segment": voc.segment(r["score"]), "comment": r["comment"],
                "sentiment": t["sentiment"], "themes": t["themes"], "follow_up": t["follow_up"], "reason": t["reason"],
                "topic_id": topics[r["id"]], "topic_by": "ai"})
        s["step"] = "Writing the summary"
        stats = voc.compute_stats(responses, tags)
        saved = {row["response_id"]: row for row in history.rows("response")}
        for f in stats["follow_up"]:
            row = saved.get(f["id"], {})
            f["topic"] = topic_info(row.get("topic_id"), row.get("topic_by", "ai"))
            f["history_id"] = row.get("id")
        with _model:
            summary, bad = voc.write_summary(stats)
        s.update(state="done", result={"group": group, "stats": stats, "summary": summary, "unsupported": bad})
    except Exception as e:
        traceback.print_exc()
        s.update(state="error", error=f"{type(e).__name__}: {e}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        self._send(status, json.dumps(payload, default=str).encode("utf-8"), "application/json")

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/status":
            return self._json({"model_ready": AppState.model_ready, "model_error": AppState.model_error,
                               "tickets": len(data.tickets()), "articles": len(data.articles()),
                               "surveys": {g: sum(r["group"] == g for r in data.surveys()) for g in ("holdout", "core")}})
        if url.path == "/api/sample":
            q = parse_qs(url.query)
            return self._json(sample(q.get("kind", ["any"])[0], q.get("id", [""])[0]))
        if url.path == "/api/survey":
            return self._json(AppState.survey)
        if url.path == "/api/articles":
            return self._json(list_articles())
        if url.path == "/api/taxonomy":
            return self._json({**taxonomy.load(), "fallback": taxonomy.FALLBACK})
        if url.path == "/api/report-options":
            return self._json(reports.options())
        if url.path == "/api/reports":
            return self._json({"reports": reports.saved()})
        name = "index.html" if url.path in ("/", "/index.html") else url.path.lstrip("/")
        file = (STATIC / name).resolve()
        if not file.is_file() or STATIC.resolve() not in file.parents:
            return self._send(404, b"Not found", "text/plain")
        self._send(200, file.read_bytes(), mimetypes.guess_type(file.name)[0] or "application/octet-stream")

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            p = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/api/triage":
                body = str(p.get("body", "")).strip()
                if not body:
                    return self._json({"error": "Type the ticket text first."}, 400)
                plan = p.get("plan") if p.get("plan") in ("Starter", "Pro", "Business") else "Pro"
                test_id = str(p.get("test_id") or "")
                test_id = test_id if any(t["id"] == test_id for t in data.tickets()) else ""
                return self._json(do_triage({"plan": plan, "subject": str(p.get("subject", ""))[:200], "body": body[:4000]}, test_id))
            if self.path == "/api/comment":
                comment = str(p.get("comment", "")).strip()
                score = int(p.get("score", -1))
                plan = p.get("plan") if p.get("plan") in ("Starter", "Pro", "Business") else "Pro"
                if not comment or not 0 <= score <= 10:
                    return self._json({"error": "Pick a score and type a comment."}, 400)
                with _model:
                    tags, secs = voc.tag({"score": score, "plan": plan, "comment": comment[:2000]})
                topic_id = suggest_topic(comment[:2000], "survey")
                hid = history.add_response({
                    "source": "typed", "month": datetime.now().strftime("%Y-%m"), "plan": plan, "score": score,
                    "segment": voc.segment(score), "comment": comment[:2000], "sentiment": tags["sentiment"],
                    "themes": tags["themes"], "follow_up": tags["follow_up"], "reason": tags["reason"],
                    "topic_id": topic_id, "topic_by": "ai"})
                return self._json({**tags, "segment": voc.segment(score), "seconds": round(secs, 1),
                                   "history_id": hid, "topic": topic_info(topic_id)})
            if self.path == "/api/topic":
                kind = "ticket" if p.get("kind") == "ticket" else "response"
                topic_id = str(p.get("topic_id", ""))
                if topic_id not in {t["id"] for t in taxonomy.topics(include_retired=True)}:
                    return self._json({"error": "Unknown topic."}, 400)
                history.set_topic(kind, int(p.get("id")), topic_id)
                return self._json({"topic": topic_info(topic_id, "you")})
            if self.path == "/api/taxonomy":
                try:
                    return self._json({**taxonomy.save(p), "fallback": taxonomy.FALLBACK})
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
            if self.path == "/api/report":
                return self._json(reports.run(clean_spec(p.get("spec") or {})))
            if self.path == "/api/reports":
                try:
                    return self._json(reports.save_report(str(p.get("name", "")), clean_spec(p.get("spec") or {}), p.get("id")))
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
            if self.path == "/api/export":
                path = reports.export_xlsx(clean_spec(p.get("spec") or {}), str(p.get("name", ""))[:80])
                return self._json({"path": str(path), "name": path.name, "folder": str(path.parent)})
            if self.path == "/api/open":
                path = Path(str(p.get("path", ""))).resolve()
                if reports.EXPORT_DIR.resolve() not in path.parents or not path.exists():
                    return self._json({"error": "Can only open files in the exports folder."}, 400)
                os.startfile(path.parent if p.get("folder") else path)
                return self._json({"opened": str(path)})
            if self.path == "/api/history/clear":
                history.clear(p.get("kind") if p.get("kind") in ("ticket", "response") else None)
                return self._json(history.counts())
            if self.path == "/api/articles":
                try:
                    saved = data.save_custom_article(str(p.get("title", "")), str(p.get("body", "")), p.get("id") or None)
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                return self._json(saved)
            if self.path == "/api/survey":
                if AppState.survey.get("state") == "running":
                    return self._json(AppState.survey)
                group = "core" if p.get("group") == "core" else "holdout"
                AppState.survey = {"state": "running", "done": 0, "total": 0, "step": "Starting"}
                threading.Thread(target=run_survey, args=(group,), daemon=True).start()
                return self._json(AppState.survey)
            self._json({"error": "Unknown endpoint."}, 404)
        except Exception as e:
            traceback.print_exc()
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)


    def do_DELETE(self):
        if self.path.startswith("/api/reports/"):
            reports.delete_report(self.path[len("/api/reports/"):])
            return self._json({"reports": reports.saved()})
        prefix = "/api/articles/"
        if not self.path.startswith(prefix):
            return self._json({"error": "Unknown endpoint."}, 404)
        article_id = self.path[len(prefix):]
        if article_id not in data.custom_articles():
            return self._json({"error": "Only your own articles can be deleted."}, 400)
        data.delete_custom_article(article_id)
        self._json({"deleted": article_id})


def start_server(port: int = 0) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
