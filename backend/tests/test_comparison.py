from app.agents.ask.comparison import extract_compare_sides, is_comparison_question


def test_compare_sl_codes():
    q = "Compare SL3000 and SL2000"
    assert is_comparison_question(q)
    sides = extract_compare_sides(q)
    assert "SL3000" in sides
    assert "SL2000" in sides


def test_vs_pattern():
    q = "SL2000 vs SL3000"
    assert is_comparison_question(q)
    assert extract_compare_sides(q)[:2] == ["SL2000", "SL3000"] or set(
        extract_compare_sides(q)[:2]
    ) == {"SL2000", "SL3000"}


def test_difference_between():
    q = "What is the difference between SL2000 and SL3000?"
    assert is_comparison_question(q)
    sides = extract_compare_sides(q)
    assert set(s.upper() for s in sides) >= {"SL2000", "SL3000"}


def test_not_comparison():
    assert not is_comparison_question("What is PlayReady?")
