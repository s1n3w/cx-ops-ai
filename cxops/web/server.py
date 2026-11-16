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
"""
import json
import mimetypes
import random
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import data, triage, voc
from ..data import QUEUES

STATIC = Path(__file__).with_name("static")
_model = threading.Lock()  # one local model: requests take turns


class AppState:
    model_ready = False
    model_error: str | None = None
    survey = {"state": "idle"}


def do_triage(ticket: dict) -> dict:
    with _model:
        t = triage.triage(ticket)
    article = data.articles().get(t.kb_id) if t.kb_id else None
    return {
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
        s["step"] = "Writing the summary"
        stats = voc.compute_stats(responses, tags)
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
                return self._json(do_triage({"plan": plan, "subject": str(p.get("subject", ""))[:200], "body": body[:4000]}))
            if self.path == "/api/comment":
                comment = str(p.get("comment", "")).strip()
                score = int(p.get("score", -1))
                if not comment or not 0 <= score <= 10:
                    return self._json({"error": "Pick a score and type a comment."}, 400)
                with _model:
                    tags, secs = voc.tag({"score": score, "plan": p.get("plan", "Pro"), "comment": comment[:2000]})
                return self._json({**tags, "segment": voc.segment(score), "seconds": round(secs, 1)})
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
