"""Picklist, history, reports, and Excel export: all code, so all testable without a model."""
import pytest
from openpyxl import load_workbook

from cxops import history, reports, taxonomy


@pytest.fixture(autouse=True)
def temp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(taxonomy, "FILE", tmp_path / "taxonomy.json")
    monkeypatch.setattr(history, "DB", tmp_path / "history.db")
    monkeypatch.setattr(reports, "SAVED", tmp_path / "reports.json")
    monkeypatch.setattr(reports, "EXPORT_DIR", tmp_path / "exports")


def ticket(**kw):
    base = {"source": "typed", "plan": "Pro", "subject": "s", "body": "b", "type": "integration", "urgency": "normal",
            "queue": "Technical", "decision": "auto", "risk_flags": [], "topic_id": "quickbooks", "topic_by": "ai"}
    return {**base, **kw}


def response(**kw):
    base = {"source": "survey run", "month": "2026-10", "plan": "Pro", "score": 9, "segment": "promoter",
            "comment": "c", "sentiment": "positive", "themes": ["integrations"], "follow_up": False,
            "topic_id": "quickbooks", "topic_by": "ai"}
    return {**base, **kw}


def test_default_taxonomy_and_lookup():
    ids = [t["id"] for t in taxonomy.topics()]
    assert len(ids) == len(set(ids)) and "quickbooks" in ids and taxonomy.FALLBACK in ids
    assert taxonomy.lookup("quickbooks")["category"] == "Integrations"
    assert taxonomy.lookup("nope")["category"] == "Uncategorized"


def test_edit_taxonomy_keeps_removed_topics_as_retired():
    tax = taxonomy.load()
    tax["categories"][0]["topics"] = [t for t in tax["categories"][0]["topics"] if t["id"] != "seats"]
    tax["categories"].append({"name": "Partners", "topics": [{"name": "Referral program"}]})
    taxonomy.save(tax)
    assert taxonomy.lookup("seats")["active"] is False            # past items keep their label
    assert "seats" not in [t["id"] for t in taxonomy.topics()]    # but the AI can't pick it any more
    assert taxonomy.lookup("referral-program")["category"] == "Partners"
    with pytest.raises(ValueError):
        taxonomy.save({"categories": [{"name": "A", "topics": [{"name": "X"}]}, {"name": "a", "topics": []}]})


def test_reports_group_split_and_metrics():
    history.add_ticket(ticket())
    history.add_ticket(ticket(decision="escalate", urgency="urgent", topic_id="charges-refunds", type="billing", queue="Billing"))
    history.add_ticket(ticket(decision="spam", topic_id="spam-not-support", type="spam"))
    r = reports.run({"kind": "ticket", "filters": {}, "group_by": "category", "split_by": "decision"})
    by = {row["group"]: row for row in r["table"]}
    assert by["Integrations"]["count"] == 1 and by["Integrations"]["auto_rate"] == 100.0
    assert by["Billing"]["urgent"] == 1 and r["totals"]["auto_rate"] == 50.0   # spam isn't counted as a real ticket
    assert r["split"]["cells"]["Billing"]["Sent to a person"] == 1
    only = reports.run({"kind": "ticket", "filters": {"category": ["Billing"]}, "group_by": "topic"})
    assert only["rows"] == 1 and only["table"][0]["group"] == "Charges & refunds"


def test_survey_nps_dedupe_and_manual_topic_survives_rerun():
    history.add_response(response(response_id="s1", score=10))
    history.add_response(response(response_id="s2", score=3, segment="detractor", follow_up=True))
    rid = history.add_response(response(response_id="s2", score=3, segment="detractor", follow_up=True))  # re-run
    history.set_topic("response", rid, "speed")
    history.add_response(response(response_id="s2", score=3, segment="detractor", topic_id="xero"))     # AI again
    assert history.counts()["responses"] == 2
    r = reports.run({"kind": "response", "filters": {}, "group_by": "topic"})
    assert {row["group"] for row in r["table"]} == {"QuickBooks", "Speed"}
    assert r["totals"]["nps"] == 0
    oct_only = reports.run({"kind": "response", "filters": {"from": "2026-11-01"}, "group_by": "plan"})
    assert oct_only["rows"] == 0


def test_saved_reports_and_excel_export():
    history.add_ticket(ticket())
    item = reports.save_report("My report", {"kind": "ticket", "filters": {}, "group_by": "topic"})
    assert any(r["id"] == item["id"] for r in reports.saved()) and any(r.get("starter") for r in reports.saved())
    reports.delete_report(item["id"])
    assert not any(r["id"] == item["id"] for r in reports.saved())
    for split in ("", "decision"):
        path = reports.export_xlsx({"kind": "ticket", "filters": {}, "group_by": "category", "split_by": split, "chart": "count"})
        wb = load_workbook(path)
        assert wb.sheetnames == ["Report", "Data", "About"]
        assert wb["Data"].max_row == 2 and wb["Data"]["F2"].value == "QuickBooks"
