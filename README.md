# CX Ops AI

Two customer-operations tools that run on a local LLM, each with its own measured accuracy:

1. **Ticket triage and auto-resolution.** It reads a support ticket, categorizes and routes it, and either
   answers it from the help center or sends it to the right queue with a reason. It never answers what a
   person should handle.
2. **Survey comment analyzer.** It tags NPS comments by theme, sentiment, and "someone should call this
   customer," computes NPS by month and plan, and writes a leadership summary whose numbers are checked
   against the data.

Everything runs on one machine (`qwen3.6:27b` via Ollama), so no customer text leaves it.

**The problem it addresses:** support teams spend hours on tickets the help center already answers, and
survey comments pile up unread while unhappy customers churn. AI can help with both, but only if the team
can trust it. That means knowing how often it's right and, more importantly, how often it does something
it shouldn't.

## Results

| Ticket triage (160 tickets, 3 identical runs) | |
|---|---|
| Right decision (answer / send to a person / spam) | **98.1%** |
| Tickets answered without a person | **63%** (92 of 145 real tickets) |
| Auto-replies that were correct | **92 of 92** |
| Replies to tickets a person should have handled | **0** |
| Spam caught / real tickets marked spam | **15 of 15** / 0 |
| Urgent tickets sent to a person | **15 of 15** |
| Time per ticket | ~2 seconds |

| Survey analyzer (200 comments, 3 identical runs) | |
|---|---|
| Customers who needed a follow-up that it flagged | **96%** (48 of 50), with 96% precision |
| Sentiment accuracy | **95%** |
| Theme tagging F1 | 85% |
| Numbers in the AI summary not found in the data | **0** |
| Time per comment | ~1 second |

On **40 new tickets and 40 new comments**, written before these versions were scored: 95% right decisions,
24 of 25 auto-replies correct, 1 reply to a ticket a person should have handled, and 12 of 13 follow-ups
flagged with no false flags.

**[RESULTS.md](RESULTS.md)** has every version, every miss, and what changed between versions and why,
including a v1 bug that would have sent a customer the model's internal "I can't answer this" note.

## How it works

The model makes judgments; code applies the policy and does the math.

**Ticket triage** ([cxops/triage.py](cxops/triage.py))
1. The model reads the ticket and the help center and returns JSON: category, urgency, risk flags (refund,
   legal, security, outage, missing money, cancellation), and which article answers it, if any.
2. Code routes it to a queue (like CRM assignment rules) and applies the escalation policy: cancellations,
   bugs, urgent or risky tickets, and anything no single article fully answers go to a person. This is
   plain code, so it's unit-tested and can't be talked out of it.
3. Only then does the model draft a reply, from that one article only. It can still decline.

**Survey analyzer** ([cxops/voc.py](cxops/voc.py))
1. The model tags each comment: themes, sentiment, follow-up (churn signal, or a problem the customer is
   still stuck on).
2. Code computes NPS by month and plan, themes by promoter/passive/detractor, and the follow-up list.
3. The model writes a summary from those numbers, and a check flags any number in it that isn't in the data.

See [docs/sample-voc-report.md](docs/sample-voc-report.md) for a full generated report.

### Example output

```
Ticket:   "Invoices stopped showing up in QuickBooks Online. The integrations page shows error QBO-401."
Decision: AUTO (integration → Technical queue), using "QuickBooks sync errors"
Reply:    Error QBO-401 means your QuickBooks connection has expired. To fix this, go to Settings >
          Integrations > QuickBooks Online, click Reconnect, and sign in again...

Ticket:   "Our card was charged $1,416 twice on the 1st... Please fix this today."
Decision: ESCALATE to Billing (urgent; risk flags: refund, money_missing)

Ticket:   "1) Our QuickBooks sync shows QBO-6000 on four invoices. 2) Separately, I was charged for 9 seats..."
Decision: ESCALATE to Billing (the article doesn't answer everything)

Ticket:   "Your payment for invoice #88231 is overdue... pay now at https://tallyline-billing-secure.net/pay"
Decision: SPAM (phishing that impersonates Tallyline billing)
```

## The data

"Tallyline" is a made-up B2B SaaS for small professional-services firms (time tracking, invoicing, client
portal, payments, integrations). The repo includes its 34-article help center, 200 support tickets, and 240
NPS responses, all invented, each with labels that follow a written [labeling guide](data/LABELING.md).
The tickets include the hard cases: angry customers with easy questions, polite customers with urgent
problems, two questions in one ticket, refund and legal threats, and phishing that looks like a real invoice.

Everything was committed before the first model run, and each holdout set before the version it tests was
scored. The git history shows the order.

## Run it

Needs Python 3.12 and [Ollama](https://ollama.com) (a 24 GB GPU for the default model). On Windows the
tools start Ollama themselves; elsewhere, run `ollama serve` first.

```
ollama pull qwen3.6:27b
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt

.venv\Scripts\pythonw -m cxops.gui         # desktop app (or build "CX Ops AI.exe" with launcher\build.bat)
.venv\Scripts\python -m cxops.app          # the same tools as a console menu
.venv\Scripts\python -m cxops.triage "How long do password reset links last?" --plan Pro
.venv\Scripts\python -m cxops.voc --report out/voc-report.md

.venv\Scripts\python -m evals.triage_eval --label mine          # score all 160 core tickets
.venv\Scripts\python -m evals.voc_eval --label mine --group holdout
.venv\Scripts\python -m pytest
```

## Layout

```
cxops/       triage.py, voc.py, data.py (loaders, validation, routing table), llm.py, ollama.py
             gui.py + web/ (desktop app: local server + a Brave app-mode window), app.py (console menu)
             The app has a Help center tab: browse and search the 34 articles, see which test tickets each
             answers, and write your own. Your articles are saved to %LOCALAPPDATA%\cx-ops-ai\my-articles.json
             and used by the app's triage, never by the scored tests.
             taxonomy.py: the shared Category > Topic picklist (editable on the Categories tab; topics are
             retired, never deleted). The model suggests a topic in its own step, so the scored pipelines
             don't change; a person can override it.
             history.py + reports.py: every ticket and survey response the app processes is saved locally
             (SQLite), and the Reports tab groups, splits, filters, saves, and exports it to Excel (.xlsx with
             Report, Data, and About sheets, in Documents\CX Ops AI exports).
assets/      icon (VectorCraft PNGs packed by make_icon.py) · launcher/ the .exe source
data/        kb/ help center · tickets/ · surveys/ · LABELING.md
evals/       triage_eval.py, voc_eval.py (results/ is gitignored)
tests/       escalation policy, scoring, NPS math, summary number check
```

Built with Claude Code. MIT license.
