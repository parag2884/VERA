from app.knowledge_os.control import evidence_quality, gap_recommendations, sla_status
from app.knowledge_os.diff import debt_trend, diff_payloads
from app.knowledge_os.proof import build_ops_report


def test_diff_payloads_summarizes_cto_change():
    older = {
        "metrics": {
            "coverage": 70,
            "debt": 18,
            "contradictions": 5,
            "topic_nodes": 40,
        },
        "edges": [
            {"id": "a", "weight": 0.5},
            {"id": "b", "weight": 0.8},
            {"id": "gone", "weight": 1.0},
        ],
    }
    newer = {
        "metrics": {
            "coverage": 72,
            "debt": 15,
            "contradictions": 2,
            "topic_nodes": 51,
        },
        "edges": [
            {"id": "a", "weight": 0.7},
            {"id": "b", "weight": 0.6},
            {"id": "new", "weight": 1.0},
        ],
    }
    d = diff_payloads(older, newer)
    assert d["coverage_delta"] == 2
    assert d["debt_delta"] == -3
    assert d["edges_strengthened"] == 1
    assert d["edges_weakened"] == 1
    assert d["edges_added"] == 1
    assert d["edges_removed"] == 1
    assert d["contradictions_delta"] == -3
    assert "Coverage +2%" in d["summary"]
    assert "Debt -3%" in d["summary"]
    assert "1 edges strengthened" in d["summary"]
    assert "3 contradictions resolved" in d["summary"]
    assert "+11 topic nodes" in d["summary"]


def test_debt_trend_prefers_month_ago_and_improving():
    points = [
        {"debt": 18, "created_at": "2026-07-20T00:00:00+00:00"},
        {"debt": 16, "created_at": "2026-08-10T00:00:00+00:00"},
        {"debt": 12, "created_at": "2026-08-23T00:00:00+00:00"},
    ]
    t = debt_trend(points)
    assert t["current"] == 12
    assert t["prior"] == 18
    assert t["label"] == "Improving"
    assert t["delta"] == -6.0


def test_ops_report_before_after_and_adoption():
    r = build_ops_report(
        points=[
            {"debt": 22, "coverage": 81, "trust": 74, "risk": "High", "created_at": "a"},
            {"debt": 14, "coverage": 89, "trust": 86, "risk": "Medium", "created_at": "b"},
        ],
        current={"debt": 14, "coverage": 89, "trust": 86, "risk": "Medium"},
        versions=[{"vs_previous": {"summary": "3 contradictions resolved"}}],
        suggested=50,
        completed=32,
        by_driver={"topics": 11, "conflicts": 9},
        remaining=["Review two untrusted sources"],
    )
    assert r["before"]["debt"] == 22
    assert r["after"]["debt"] == 14
    assert r["adoption"]["completed"] == 32
    assert r["adoption"]["rate"] == 0.64
    assert "Debt 22% → 14%" in r["improvements"]
    assert r["has_history"]


def test_gap_recs_and_sla():
    recs = gap_recommendations(
        {
            "domains": [
                {"section": "security", "pages": 10, "linked_pages": 2, "coverage_pct": 20}
            ]
        },
        [{"title": "https://example.com/products/security"}],
    )
    assert recs
    assert recs[0]["expected_coverage_gain"] > 0
    sla = sla_status(coverage=92, debt=8, contradictions=2)
    assert sla["passing"]
    miss = sla_status(coverage=100, debt=8, contradictions=12)
    assert not miss["passing"]
    assert miss["cta"] == "scan_conflicts"
    assert "Scan conflicts" in (miss["next"] or "")
    eq = evidence_quality(
        trust_pct=80, coverage_pct=90, conflict_count=0, freshness_avg_days=10
    )
    assert eq["score"] > 50


def test_care_briefing_defers_when_busy_and_asks_human_for_connect():
    from app.knowledge_os.care import briefing

    d = briefing(sla={"passing": True}, ingest_busy=True, forge_busy=False, node_count=10)
    assert d["mode"] == "defer"
    assert d["human"] is False
    h = briefing(
        sla={"passing": False, "cta": "connect", "next": "Ingest more."},
        ingest_busy=False,
        forge_busy=False,
        node_count=4,
    )
    assert h["human"] is True
    assert h["cta"] == "connect"
    a = briefing(
        sla={"passing": False, "cta": "scan_conflicts", "next": "Scan."},
        ingest_busy=False,
        forge_busy=False,
        node_count=4,
    )
def test_operate_hygiene_and_window():
    from app.knowledge_os.care import CARE_MUST_NOT
    from app.knowledge_os.hygiene import scan
    from app.knowledge_os.operate import (
        drift_flags,
        in_maintenance_window,
        recommended_today,
        weekly_summary,
    )

    g = {
        "nodes": [
            {"id": "a", "name": "Auth", "normalized_name": "auth", "type": "topic"},
            {"id": "b", "name": "Auth", "normalized_name": "auth", "type": "topic"},
            {"id": "c", "name": "Lonely", "type": "concept"},
        ],
        "edges": [
            {
                "id": "e1",
                "src": "a",
                "dst": "missing",
                "edge_class": "asserted_fact",
                "weight": 0.2,
                "status": "active",
            }
        ],
    }
    h = scan(g, path_stats={"p": (0, 5)}, docs=[{"title": "https://ex.com/a"}])
    assert h["counts"]["broken_links"] >= 1
    assert h["counts"]["duplicate_entities"] >= 1
    assert h["counts"]["weak_edges"] >= 1
    assert h["counts"]["stale_paths"] >= 1
    assert in_maintenance_window(hour_utc=2, start_hour=2, duration_hours=3)
    assert not in_maintenance_window(hour_utc=12, start_hour=2, duration_hours=3)
    flags = drift_flags(
        [{"debt": 12, "coverage": 90, "trust": 80, "contradictions": 1, "refusals": 0}],
        {"debt": 19, "coverage": 90, "trust": 80, "contradictions": 1, "refusals": 0},
    )
    assert any(f["metric"] == "Debt" for f in flags)
    rec = recommended_today(
        {
            "current_debt": 12,
            "actions": [
                {
                    "do": "Link Authentication topic",
                    "expected_debt_after_this": 10,
                    "driver": "topics",
                }
            ],
        },
        [],
    )
    assert rec[0]["title"] == "Link Authentication topic"
    assert rec[0]["expected_debt_delta"] == -2.0
    assert rec[0]["policy"] is False
    week = weekly_summary(
        [{"coverage": 90, "debt": 14, "trust": 80, "contradictions": 5}],
        {"coverage": 92, "debt": 11, "trust": 81, "contradictions": 2},
        risk="Low",
    )
    assert week and "Coverage: +2.0%" in week["text"]
    assert "Debt: -3.0%" in week["text"]
def test_principles_classify():
    from app.knowledge_os.principles import GOVERN, MAINTAIN, OBSERVE, classify, public_card

    assert classify("hygiene_scan") == OBSERVE
    assert classify("conflict_edges") == MAINTAIN
    assert classify("accept_drafts") == GOVERN
    assert public_card()["rule"].startswith("Care can observe")
