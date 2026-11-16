"""Number crunching and the summary check run in code, so they're testable without a model."""
from cxops import voc


def test_nps_and_segments():
    assert voc.nps([10, 9, 8, 7, 6, 0]) == 0          # 2 promoters, 2 detractors of 6
    assert voc.nps([10, 10, 9]) == 100
    assert voc.segment(9) == "promoter" and voc.segment(7) == "passive" and voc.segment(6) == "detractor"


def test_stats_and_follow_up_order():
    rs = [{"id": "a", "score": 10, "plan": "Pro", "month": "2026-10", "comment": "great"},
          {"id": "b", "score": 2, "plan": "Pro", "month": "2026-10", "comment": "leaving"},
          {"id": "c", "score": 5, "plan": "Starter", "month": "2026-09", "comment": "slow"}]
    tags = {"a": {"themes": ["ease_of_use"], "follow_up": False, "reason": ""},
            "b": {"themes": ["billing_pricing"], "follow_up": True, "reason": "churn"},
            "c": {"themes": ["performance"], "follow_up": True, "reason": "slow"}}
    s = voc.compute_stats(rs, tags)
    assert s["nps"] == -33 and s["detractors"] == 2
    assert [f["id"] for f in s["follow_up"]] == ["b", "c"]
    assert dict(s["detractor_themes"]) == {"billing_pricing": 1, "performance": 1}


def test_unsupported_numbers_flags_invented_values():
    stats = {"nps": 42, "responses": 200, "nps_by_month": {"2026-10": {"nps": 38, "responses": 100}}, "follow_up": []}
    assert voc.unsupported_numbers("NPS is 42 across 200 responses; October was 38.", stats) == []
    assert voc.unsupported_numbers("NPS rose 4 points to 46.", stats) == ["4", "46"]


def test_normalize_drops_unknown_themes():
    n = voc.normalize({"themes": ["mobile", "vibes"], "sentiment": "angry", "follow_up": "yes"})
    assert n == {"themes": ["mobile"], "sentiment": "neutral", "follow_up": False, "reason": ""}
