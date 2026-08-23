from app.knowledge.sources.web.site_graph import parent_path, trust_weight
from app.knowledge_os.learn import as_of_iso, heading_topic
from app.knowledge_os.conflicts import parse_amount
from app.knowledge_os.coverage import section_for_title
from app.knowledge_os.debt import knowledge_debt, improvement_loop


def test_parent_path_and_trust():
    assert parent_path("/about-us/leaders") == "/about-us"
    assert trust_weight("https://x.com/about/leaders") > trust_weight(
        "https://x.com/news/press-2024"
    )


def test_html_keeps_headings():
    import importlib.util

    if importlib.util.find_spec("bs4") is None:
        return
    from app.knowledge.sources.web.html_extract import extract_html_text

    html = """
    <html><head><title>Auth</title></head>
    <body>
      <nav>Home About</nav>
      <main>
        <h1>Authentication</h1>
        <h2>OAuth</h2>
        <p>Azure OpenAI supports OAuth tokens.</p>
        <ul><li>Access token</li><li>Refresh token</li></ul>
      </main>
    </body></html>
    """
    text = extract_html_text(html, "https://example.com/docs/auth")
    assert "Authentication" in text
    assert "OAuth" in text
    assert "Access token" in text


def test_parse_amount_and_sections():
    assert parse_amount("Loan Amount = $500,000") == 500000.0
    assert parse_amount("Loan Amount = $450,000") == 450000.0
    assert section_for_title("https://x.com/about-us/leaders") == "identity"
    assert section_for_title("https://x.com/news/press") == "chronicle"


def test_topic_and_as_of():
    assert heading_topic("# Authentication\n\nOAuth tokens") == "Authentication"
    assert as_of_iso("Appointed CEO in 2022. Updated 2025.") == "2025-01-01"


def test_knowledge_debt_lower_when_healthy():
    healthy = knowledge_debt(
        coverage_pct=91,
        source_reliability=0.88,
        conflict_count=0,
        weak_edge_count=1,
        asserted_edges=50,
        unanswered=1,
        gap_sections=0,
    )
    sick = knowledge_debt(
        coverage_pct=40,
        source_reliability=0.4,
        conflict_count=8,
        weak_edge_count=20,
        asserted_edges=40,
        unanswered=12,
        gap_sections=4,
    )
    assert healthy["score"] < 20
    assert sick["score"] > healthy["score"]
    assert sick["status"] == "elevated"
    assert sick["risk"]["level"] == "High"
    loop = improvement_loop(sick, {"topics": [{"section": "security"}]})
    assert loop["expected_debt_after_fix"] < loop["current_debt"]
    assert loop["actions"]


def test_debt_drilldown_weak_edge_success():
    from app.knowledge_os.debt import debt_drilldown

    graph = {
        "nodes": [
            {"id": "n1", "name": "OAuth"},
            {"id": "n2", "name": "Authentication"},
        ],
        "edges": [
            {
                "id": "e1",
                "src": "n1",
                "dst": "n2",
                "rel_type": "RELATED_TO",
                "edge_class": "asserted_fact",
                "status": "active",
                "weight": 0.4,
            }
        ],
    }
    dd = debt_drilldown(
        graph=graph,
        path_stats={"e1": (48, 52)},
        docs=[],
        cover={
            "domains": [
                {"section": "security", "pages": 10, "linked_pages": 4, "coverage_pct": 40}
            ],
            "gap_sections": ["security"],
        },
        conflicts=[],
        drafts=[],
        production_weak=[],
    )
    assert dd["weak_edges"][0]["from"] == "OAuth"
    assert dd["weak_edges"][0]["to"] == "Authentication"
    assert dd["weak_edges"][0]["success_rate"] == 48.0
    assert dd["topics"][0]["expected_coverage_gain"] == 60.0
