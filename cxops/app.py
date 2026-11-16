"""Interactive menu for trying both tools by hand. Starts Ollama and stops it when you quit.

Run:  python -m cxops.app      (or double-click "CX Ops AI.exe")
"""
import os
import random
import subprocess
import sys
import textwrap

from . import ROOT, data, llm, triage, voc
from .ollama import ensure_running

LINE = "-" * 72


def wrap(text: str, indent: str = "  ") -> str:
    return "\n".join(textwrap.fill(p, 72, initial_indent=indent, subsequent_indent=indent) if p.strip() else ""
                     for p in text.splitlines())


def ask(prompt: str, default: str = "") -> str:
    value = input(prompt).strip()
    return value or default


def read_body() -> str:
    print("Ticket text (press Enter on an empty line when done):")
    lines = []
    while True:
        line = input("  ")
        if not line and lines:
            break
        if line:
            lines.append(line)
    return "\n".join(lines)


def show_triage(t, gold: dict | None = None) -> None:
    print(LINE)
    print(f"Category: {t.category}    Urgency: {t.urgency}    Queue: {t.queue}")
    if t.resolution == "auto":
        a = data.articles()[t.kb_id]
        print(f"Decision: AUTO-REPLY, using [{t.kb_id}] {a['title']}\n")
        print(wrap(t.reply))
    elif t.resolution == "spam":
        print(f"Decision: SPAM ({t.why.removeprefix('spam: ')})")
    else:
        print(f"Decision: SEND TO A PERSON in {t.queue}: {t.why}")
    if t.risk_flags:
        print(f"Risk flags: {', '.join(t.risk_flags)}")
    print(f"\n({t.seconds:.1f}s)")
    if gold:
        ok = lambda a, b: "match" if a == b else "DIFFERENT"
        print(f"\nCorrect answer from the test set: {gold['category']}, {gold['urgency']}, {gold['resolution']}"
              f"   [category {ok(t.category, gold['category'])}, decision {ok(t.resolution, gold['resolution'])}]")
        if gold.get("note"):
            print(wrap("Note: " + gold["note"]))
    print(LINE)


def type_a_ticket() -> None:
    plan = ask("Customer's plan - Starter, Pro, or Business [Pro]: ", "Pro").title()
    if plan not in ("Starter", "Pro", "Business"):
        plan = "Pro"
    subject = ask("Subject (optional): ")
    body = read_body()
    print("\nWorking...")
    show_triage(triage.triage({"plan": plan, "subject": subject, "body": body}))


def sample_ticket() -> None:
    t = random.choice(data.tickets())
    print(f"\nSample {t['id']} ({t['plan']} plan)\nSubject: {t['subject']}\n{wrap(t['body'])}\n\nWorking...")
    show_triage(triage.triage(t), gold=t)


def type_a_comment() -> None:
    while True:
        try:
            score = int(ask("Score 0-10 (how likely to recommend): "))
            if 0 <= score <= 10:
                break
        except ValueError:
            pass
        print("Please enter a number from 0 to 10.")
    plan = ask("Plan [Pro]: ", "Pro").title()
    comment = ask("Comment: ")
    print("\nWorking...")
    tags, secs = voc.tag({"score": score, "plan": plan, "comment": comment})
    print(LINE)
    print(f"Segment: {voc.segment(score)}    Sentiment: {tags['sentiment']}")
    print(f"Themes: {', '.join(tags['themes']) or '(none)'}")
    print(f"Follow up with this customer: {'YES' if tags['follow_up'] else 'no'}")
    print(wrap("Why: " + tags["reason"]))
    print(f"\n({secs:.1f}s)\n{LINE}")


def survey_report() -> None:
    print("\n  1  Quick: the 40 newest responses (about 30 seconds)")
    print("  2  Full: all 200 core responses (about 3 minutes)")
    group = "holdout" if ask("Choose [1]: ", "1") != "2" else "core"
    responses = [r for r in data.surveys() if r["group"] == group]
    tags = {}
    for i, r in enumerate(responses, 1):
        tags[r["id"]], _ = voc.tag(r)
        print(f"\r  Tagged {i}/{len(responses)}", end="", flush=True)
    print("\n  Writing the summary...")
    stats = voc.compute_stats(responses, tags)
    summary, bad = voc.write_summary(stats)
    out = ROOT / "out" / f"voc-report-{group}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(voc.report_markdown(stats, summary, bad), encoding="utf-8")
    print(f"\n{LINE}\nNPS {stats['nps']} from {stats['responses']} responses. "
          f"{stats['follow_up_count']} customers flagged for follow-up.\n")
    print(wrap(summary))
    if bad:
        print(f"\nCheck: numbers not found in the data: {', '.join(bad)}")
    print(f"\nFull report saved to {out}\n{LINE}")
    if ask("Open the full report in Notepad? [y/N]: ").lower().startswith("y"):
        subprocess.Popen(["notepad.exe", str(out)])


MENU = [
    ("Triage a ticket you type", type_a_ticket),
    ("Triage a random ticket from the test set (shows the correct answer)", sample_ticket),
    ("Analyze one survey comment you type", type_a_comment),
    ("Run the survey report (NPS, themes, follow-up list, AI summary)", survey_report),
]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    os.system("title CX Ops AI")
    print("CX Ops AI: support-ticket triage and survey analysis on a local model\n")
    print("Starting Ollama and loading the model (first time takes a few seconds)...", flush=True)
    with ensure_running():
        llm.chat([{"role": "user", "content": "Reply OK."}])
        while True:
            print("\nWhat would you like to try?")
            for i, (label, _) in enumerate(MENU, 1):
                print(f"  {i}  {label}")
            print("  Q  Quit")
            choice = ask("> ").lower()
            if choice in ("q", "quit", "exit"):
                break
            if choice.isdigit() and 1 <= int(choice) <= len(MENU):
                try:
                    MENU[int(choice) - 1][1]()
                except KeyboardInterrupt:
                    print("\n(cancelled)")
                except Exception as e:  # keep the menu alive for a hands-on test
                    print(f"\nSomething went wrong: {e}")
        print("Stopping Ollama...")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        pass
