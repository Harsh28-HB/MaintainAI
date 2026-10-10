from src.retrieval import load_manual_sections, search_manuals

sections = load_manual_sections()

assert sections, "No manual sections were loaded."
print(f"PASS: Loaded {len(sections)} manual sections")

# Search for vibration-related evidence
results = search_manuals("excessive vibration and bearing wear")

assert results, "Expected vibration-related results."
assert any(
    "Vibration" in result["heading"]
    for result in results
), "The vibration section was not retrieved."

print("PASS: Relevant vibration section retrieved")
print("Citation:", results[0]["citation"])
print("Evidence:", results[0]["content"])

# Search for temperature-related evidence
temperature_results = search_manuals("high bearing temperature lubrication")

assert temperature_results, "Expected temperature-related results."
assert any(
    "Temperature" in result["heading"]
    for result in temperature_results
), "The temperature section was not retrieved."

print("PASS: Relevant temperature section retrieved")

# Empty query must return no results
assert search_manuals("   ") == []
print("PASS: Empty query handled")

# Unrelated query must not fabricate evidence
assert search_manuals("spacecraft moon landing") == []
print("PASS: No-match query handled")

print("\nAll retrieval checks passed!")
