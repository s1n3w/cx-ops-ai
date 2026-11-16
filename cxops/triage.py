"""Support-ticket triage and auto-resolution.

1. The model classifies the ticket (category, urgency, risk flags) and picks the help article that
   answers it, if any.
2. Code applies the escalation policy (like CRM assignment rules): cancellations, bugs, urgent
   tickets, refunds, legal, security, outages, and anything no single article covers go to a human.
3. Only then does the model draft a reply, using that one article and nothing else. It can still
   decline with ESCALATE.

Run:  python -m cxops.triage "My QuickBooks sync shows error QBO-401" [--subject ...] [--plan Pro]
"""
import argparse
import re
import sys
import time
from dataclasses import dataclass, field

from . import data, llm
from .data import CATEGORIES, QUEUES, URGENCIES

RISK_FLAGS = ["refund", "cancellation", "legal", "security", "outage_or_data_loss", "money_missing"]
ALWAYS_HUMAN = {"cancellation", "bug"}

COMPANY = ("Tallyline is a B2B SaaS for small professional-services firms: time tracking, invoicing, "
           "a client portal, online payments, and integrations. Plans: Starter, Pro, Business.")

CATEGORY_HELP = """\
- billing: Tallyline's own subscription: plans, prices, charges, cards, receipts, seats, refunds
- access: can't log in, passwords, 2FA, SSO, inviting users, account ownership, suspicious sign-ins
- bug: something in the product is broken or behaving wrong (errors, crashes, wrong numbers, slowness, outages)
- how_to: how to use a feature (invoices, templates, reminders, payments, portal, reports, mobile app, expenses, taxes)
- feature_request: asks for something the product doesn't do
- integration: QuickBooks, Xero, Google/Outlook calendar, Zapier, the API
- data_import: importing or exporting data (CSV import, full data export, data requests)
- cancellation: wants to cancel or close the account
- spam: not a real support request (sales pitches, SEO/marketing offers, partnership pitches, phishing, scams, gibberish)
When two fit, prefer the specific area: a problem with payouts or charges is billing, with sign-in or SSO is access,
with QuickBooks/Xero/calendars/Zapier/the API is integration, with importing or exporting is data_import, even if
something is broken or it's a how-to question. Use bug for broken core features (timesheets, timers, invoices,
reports, the portal, the app being down or slow) and how_to for using those core features."""

URGENCY_HELP = """\
- urgent: work is stopped for many people; money is moving wrongly (double charges, missing or misdirected payouts);
  possible security or privacy problem; data loss; or a legal threat
- low: feature requests, general questions with no deadline, spam
- normal: everything else (a customer shouting "urgent" about a simple question is still normal)"""


def _kb_block() -> str:
    return "\n\n".join(f"[{a['id']}] {a['title']}\n{a['body']}" for a in data.articles().values())


def classify_messages(ticket: dict) -> list[dict]:
    system = f"""You triage support tickets for Tallyline. {COMPANY}

Categories (pick the customer's main ask):
{CATEGORY_HELP}

Urgency:
{URGENCY_HELP}

Risk flags (list every one that applies, or none): {", ".join(RISK_FLAGS)}

Help-center articles:
{_kb_block()}

Choose kb_id = the one article that answers the ticket, or null if none does. Set covered = true only if that
article alone fully answers every question in the ticket, with nothing left that needs a person to look up,
change, or decide something for this customer.

Reply with JSON only:
{{"category": "...", "urgency": "...", "risk_flags": [], "kb_id": "kb00 or null", "covered": true, "reason": "one short sentence"}}"""
    user = f"Plan: {ticket.get('plan', 'unknown')}\nSubject: {ticket.get('subject', '')}\n\n{ticket['body']}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def draft_messages(ticket: dict, article: dict) -> list[dict]:
    system = f"""You are a Tallyline support agent. {COMPANY}
Answer the customer using ONLY the help article below. Include the exact menu paths, numbers, time limits,
and plan names from the article that answer their question. Be warm and brief (under 120 words), no sign-off
name, no promises the article doesn't make, no links except ones in the article.
If the article does not fully answer the question, reply with exactly: ESCALATE

Help article [{article['id']}] {article['title']}:
{article['body']}"""
    user = f"Subject: {ticket.get('subject', '')}\n\n{ticket['body']}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


@dataclass
class Triage:
    category: str
    urgency: str
    queue: str
    resolution: str            # auto | escalate | spam
    kb_id: str | None
    risk_flags: list = field(default_factory=list)
    reply: str = ""
    why: str = ""              # escalation reason or the model's note
    seconds: float = 0.0
    tokens: int = 0


def escalation_reason(c: dict) -> str | None:
    """The escalation policy, applied in code. Returns why a human is needed, or None."""
    if c["category"] in ALWAYS_HUMAN:
        return f"{c['category']} tickets always go to a person"
    if c["urgency"] == "urgent":
        return "urgent"
    if c["risk_flags"]:
        return "risk: " + ", ".join(c["risk_flags"])
    if not c["kb_id"]:
        return "no help article covers this"
    if not c["covered"]:
        return "the article doesn't answer everything"
    return None


def normalize(raw: dict) -> dict:
    """Clamp the model's JSON to known values so one odd answer can't break routing."""
    kb = raw.get("kb_id")
    kb = kb if isinstance(kb, str) and kb in data.articles() else None
    cat = raw.get("category") if raw.get("category") in CATEGORIES else "how_to"
    urg = raw.get("urgency") if raw.get("urgency") in URGENCIES else "normal"
    flags = [f for f in (raw.get("risk_flags") or []) if f in RISK_FLAGS]
    return {"category": cat, "urgency": urg, "risk_flags": flags, "kb_id": kb,
            "covered": raw.get("covered") is True, "reason": str(raw.get("reason", ""))}


def triage(ticket: dict, model: str = llm.DEFAULT_MODEL) -> Triage:
    started = time.time()
    raw, rep = llm.chat_json(classify_messages(ticket), model)
    tokens = rep.prompt_tokens + rep.output_tokens
    c = normalize(raw)
    t = Triage(c["category"], c["urgency"], QUEUES[c["category"]], "escalate", c["kb_id"], c["risk_flags"],
               why=c["reason"])
    if c["category"] == "spam":
        t.resolution, t.why = "spam", "spam: " + c["reason"]
    elif (reason := escalation_reason(c)):
        t.why = reason
    else:
        rep = llm.chat(draft_messages(ticket, data.articles()[c["kb_id"]]), model)
        tokens += rep.prompt_tokens + rep.output_tokens
        text = rep.text.strip()
        # v2 fix: the model sometimes explains first and says ESCALATE at the end. Never send that.
        if re.search(r"\bESCALATE\b", text):
            t.why = "the drafted reply declined (article doesn't cover it)"
        else:
            t.resolution, t.reply = "auto", text
    t.seconds, t.tokens = time.time() - started, tokens
    return t


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Triage one support ticket.")
    p.add_argument("body")
    p.add_argument("--subject", default="")
    p.add_argument("--plan", default="Pro", choices=["Starter", "Pro", "Business"])
    a = p.parse_args()
    from .ollama import ensure_running
    with ensure_running():
        t = triage({"subject": a.subject, "body": a.body, "plan": a.plan})
    print(f"Category: {t.category}   Urgency: {t.urgency}   Queue: {t.queue}")
    print(f"Decision: {t.resolution.upper()}" + (f" ({t.why})" if t.resolution != "auto" else f" using {t.kb_id}"))
    if t.reply:
        print("\n" + t.reply)
    print(f"\n[{t.seconds:.1f}s, {t.tokens:,} tokens]")


if __name__ == "__main__":
    main()
