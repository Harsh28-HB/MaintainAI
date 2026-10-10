
from __future__ import annotations

import re
from pathlib import Path
from collections import Counter
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANUALS_DIR = PROJECT_ROOT / "data" / "manuals"

STOP_WORDS = {
    "the", "a", "an", "and", "or", "is", "are", "was", "were",
    "to", "of", "in", "on", "for", "with", "by", "from", "it",
    "this", "that", "as", "at", "be", "has", "have", "had",
    "what", "which", "how", "my", "our", "your", "about",
}


def tokenize(text: str) -> list[str]:
    """Normalize text into searchable terms."""
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [word for word in words if word not in STOP_WORDS]


def load_manual_sections(
    manuals_dir: Path | str = DEFAULT_MANUALS_DIR,
) -> list[dict[str, Any]]:
    """
    Load Markdown manuals and split them into sections.

    Each section retains its source filename, heading, and line numbers
    so the UI can show traceable evidence.
    """
    directory = Path(manuals_dir)

    if not directory.exists() or not directory.is_dir():
        raise FileNotFoundError(
            f"Manual directory does not exist: {directory}"
        )

    sections = []

    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()

        current_heading = path.stem
        current_lines: list[str] = []
        start_line = 1

        def save_section(end_line: int) -> None:
            content = "\n".join(current_lines).strip()
            if not content:
                return

            sections.append({
                "source": path.name,
                "heading": current_heading,
                "start_line": start_line,
                "end_line": end_line,
                "content": content,
            })

        for line_number, line in enumerate(lines, start=1):
            heading_match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)

            if heading_match:
                save_section(line_number - 1)
                current_heading = heading_match.group(1).strip()
                current_lines = [line]
                start_line = line_number
            else:
                if not current_lines:
                    start_line = line_number
                current_lines.append(line)

        save_section(len(lines))

    return sections


def search_manuals(
    query: str,
    manuals_dir: Path | str = DEFAULT_MANUALS_DIR,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """
    Rank manual sections with deterministic lexical matching.

    This lightweight retrieval approach does not require an embedding
    API. It is suitable for the bounded demonstration knowledge base.
    """
    if not isinstance(query, str) or not query.strip():
        return []

    if top_k < 1:
        raise ValueError("top_k must be at least 1.")

    sections = load_manual_sections(manuals_dir)
    query_terms = tokenize(query)

    if not query_terms:
        return []

    query_counts = Counter(query_terms)
    scored_sections = []

    for section in sections:
        document_text = section["heading"] + " " + section["content"]
        document_counts = Counter(tokenize(document_text))

        score = 0.0

        for term, query_count in query_counts.items():
            frequency = document_counts.get(term, 0)
            if frequency:
                # Heading matches receive extra weight.
                heading_frequency = Counter(
                    tokenize(section["heading"])
                ).get(term, 0)

                score += query_count * (
                    2.0 * min(heading_frequency, 1)
                    + min(frequency, 3) * 0.5
                )

        if score > 0:
            scored_sections.append({
                **section,
                "score": round(score, 3),
                "citation": (
                    f"{section['source']} | {section['heading']} | "
                    f"lines {section['start_line']}-"
                    f"{section['end_line']}"
                ),
            })

    scored_sections.sort(
        key=lambda item: (
            -item["score"],
            item["source"],
            item["start_line"],
        )
    )

    return scored_sections[:top_k]


def format_evidence(
    results: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Return compact evidence records for the UI and AI prompt."""
    return [
        {
            "citation": result["citation"],
            "content": result["content"],
        }
        for result in results
    ]
