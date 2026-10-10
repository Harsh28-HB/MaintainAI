from src.retrieval import load_manual_sections, search_manuals


def test_manual_sections_load():
    sections = load_manual_sections()
    assert sections


def test_vibration_search_returns_evidence():
    results = search_manuals("excessive vibration bearing wear")

    assert results
    assert any("Vibration" in item["heading"] for item in results)
    assert all(item["citation"] for item in results)


def test_empty_query_returns_no_results():
    assert search_manuals("   ") == []


def test_unrelated_query_returns_no_results():
    assert search_manuals("spacecraft moon landing") == []
