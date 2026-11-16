# Results

All runs: `qwen3.6:27b` on Ollama, temperature 0, one RTX 4090. The data was written and committed before
the first model run (commit `66e44d2`), and each holdout set was committed before the version it tests was
first scored. Raw per-item results are written to `evals/results/` (not committed).

## Ticket triage

| Version | Set | Right decision¹ | Auto-replies | Correct replies | Unsafe² | Spam caught | Urgent sent to a person | Category |
|---|---|---|---|---|---|---|---|---|
| v1 (untuned) | core, 160 | 98.1% | 94 | 92 (97.9%) | 1 | 15/15 | n/a | 91.2% |
| **v2** | **core, 160** | **98.1%** | **92** | **92 (100%)** | **0** | **15/15** | **15/15** | **93.8%** |
| v2, unchanged | holdout, 40 | 95.0% | 25 | 24 (96.0%) | 1 | 3/3 | 6/6 | 92.5% |

¹ auto-reply vs. send to a person vs. spam. ² replied to a ticket that the labels say a person must handle.

v2 on the core set was run three times with identical results. Median time per ticket: 2.1 seconds
(p90 2.6 s). 63% of real core tickets (92 of 145) and 68% of holdout tickets (25 of 37) were resolved
without a person; the rest were routed to a queue with a reason.

**What changed from v1 to v2** (after reading v1's misses):
- **A real bug.** v1's one unsafe reply (t098) was the model doing the right thing: it explained that the
  article didn't cover the question and then wrote ESCALATE at the end. The code only checked the start of
  the reply, so it would have sent that explanation to the customer. v2 escalates if ESCALATE appears anywhere.
- **A grader error.** v1's one "incomplete" reply (t038) said "signing out" where the grader required
  "sign out". The reply was right; the required fact now accepts both.
- **A category tie-break rule** in the prompt: a broken payout is billing, a QuickBooks question is
  integration, and so on, even when something is broken or it's a how-to question. My labels already
  followed this convention but the guide didn't say so.
- A metric for urgent tickets: the model labeled 13 of 15 urgent tickets "urgent" with no false alarms, and
  all 15 still went to a person, because the risk flags or the category rules caught the other two.

**Holdout misses (v2 unchanged):**
- **h024, unsafe:** "late fees charged twice." The model answered from the reminders article (fees are
  added each time a reminder goes out, so check the reminder settings). That may well be the answer, but
  the label says a person should check whether it's a defect, so it counts against the system.
- **h018, missed automation:** the model escalated a question one article answers (billable expenses). That
  costs a person a few minutes but is safe.
- Urgency: 3 of 6 urgent holdout tickets were labeled urgent (an overcharge, a late payout, and a subpoena
  were called "normal"), but all 6 were still sent to a person.

Urgency accuracy (84% core, 78% holdout) is mostly low-vs-normal disagreement. My own labels aren't
consistent there ("how much is Business?" is normal, "how much do the plans cost?" is low), so I don't
treat that number as meaningful. Urgent detection is the part that matters.

## Survey comment analyzer

| Version | Set | Theme F1 (P / R) | Sentiment | Follow-up recall | Follow-up precision | Invented numbers in summary |
|---|---|---|---|---|---|---|
| v1 (untuned) | core, 200 | 85.5% (80.5 / 91.2) | 97.0% | 100% (50/50) | 73.5% | 0 |
| **v2** | **core, 200** | **84.7% (80.0 / 90.0)** | **95.0%** | **96.0% (48/50)** | **96.0%** | **0** |
| v2, unchanged | holdout, 40 | 88.9% (89.8 / 88.0) | 95.0% | 92.3% (12/13) | 100% | 0³ |

³ The check first flagged two numbers ($57 and $19) that the summary quoted from a customer's comment. That
was a bug in the check (it ignored the example comments the model is given); after the fix, every saved
summary passes. The fix is covered by a unit test.

v2 on the core set was run three times with identical results. Median 0.8 seconds per comment.

**What changed from v1 to v2:** v1 flagged 18 extra customers for follow-up, all detractors with a feature
wish or a general opinion ("Needs more report types", "Too many clicks"). My labeling guide's wording
("a detractor with a specific, fixable complaint") honestly supports that reading, so I clarified the rule:
feature wishes and opinions are product feedback unless the customer is leaving or stuck waiting on us.
Precision went from 73.5% to 96.0%; recall went from 100% to 96.0%. The two core customers v2 misses
(s067: SSO outage and a status page that said everything was fine; s083: Xero sync drops and they want an
alert) and the one holdout miss (x010, the same Xero complaint) are real follow-ups. It's a trade-off a team
could set the other way.

The summary prompt now also forbids claiming causes the data doesn't show (v1 said October's NPS was
"driven by" a jump in response volume).

**Theme tagging** is the weakest part, and partly because of my labels. Of v1's extra tags, many are
defensible: "Mobile app logs me out constantly" was labeled mobile only, and the model also tagged
bugs_reliability. I report the score against the original labels rather than relabel after seeing the
model's answers.

## Caveats

- Claude wrote the help center, the tickets, the survey comments, and the labels. The holdout sets were
  written before the versions they test were scored, but by the same author, so they aren't fully
  independent. Questions written by other people would be a stronger test.
- 160 + 40 tickets and 200 + 40 comments are small samples: one ticket is 0.6 points on the core set and
  2.5 points on the holdout set.
- The company, its help center, and every ticket and comment are made up. Real tickets are messier
  (attachments, long threads, other languages).
