"""Record text is data, never instructions (END_TO_END_ITSM.md §9).

`wrap` marks text from ServiceNow records before it reaches an LLM, the same way the change repository does
(`<record_data>`); a closing tag inside the text cannot end the block early. `markers` is the one marker scan:
the change repository's `INJECTION_MARKERS` plus the orchestrator's own. Finding a marker never removes text;
the caller writes a note and holds the decision.
"""
from __future__ import annotations

from cm_agents.enablement.guard import INJECTION_MARKERS

EXTRA_MARKERS = ("ignore previous", "you are now")
MARKERS = tuple(dict.fromkeys((*INJECTION_MARKERS, *EXTRA_MARKERS)))
TAG = "record_data"


def markers(*texts: str | None) -> list[str]:
    folded = "\n".join(t or "" for t in texts).casefold()
    return [m for m in MARKERS if m in folded]


def wrap(text: str | None, source: str) -> str:
    """`text` inside a record_data block naming its source (table.field or record number)."""
    body = (text or "").replace(f"</{TAG}", f"&lt;/{TAG}")
    src = "".join(c for c in source if c.isalnum() or c in "._-:")
    return f'<{TAG} source="{src}">\n{body}\n</{TAG}>'
