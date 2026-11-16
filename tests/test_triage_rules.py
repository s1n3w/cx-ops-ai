"""The escalation policy is code, so it can be tested without a model."""
from cxops import data
from cxops.triage import escalation_reason, normalize


def c(**kw):
    base = {"category": "how_to", "urgency": "normal", "risk_flags": [], "kb_id": "kb01", "covered": True}
    return normalize({**base, **kw})


def test_answerable_how_to_is_allowed():
    assert escalation_reason(c()) is None


def test_cancellations_and_bugs_always_escalate():
    assert escalation_reason(c(category="cancellation"))
    assert escalation_reason(c(category="bug"))


def test_urgent_and_risky_escalate():
    assert escalation_reason(c(urgency="urgent"))
    for flag in ["refund", "legal", "security", "outage_or_data_loss", "money_missing", "cancellation"]:
        assert escalation_reason(c(risk_flags=[flag]))


def test_no_article_or_partial_coverage_escalates():
    assert escalation_reason(c(kb_id=None))
    assert escalation_reason(c(kb_id="kb999"))      # unknown ids are dropped
    assert escalation_reason(c(covered=False))
    assert escalation_reason(c(covered="true"))      # only a real boolean true counts


def test_unknown_values_are_clamped():
    n = normalize({"category": "weird", "urgency": "asap", "risk_flags": ["refund", "made_up"]})
    assert n["category"] in data.CATEGORIES and n["urgency"] in data.URGENCIES
    assert n["risk_flags"] == ["refund"]


def test_fact_matching():
    assert data.fact_found("60 minutes|1 hour", "The link lasts ONE HOUR... I mean 1 hour")
    assert not data.fact_found("Retry payment", "click retry")


def test_gold_data_is_valid():
    assert data.validate() == []
