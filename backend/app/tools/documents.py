"""The search_documents tool: its definition for the model, and the code that runs it."""

from app.auth.access import Access
from app.config import settings
from app.ingest.store import get_store

NAME = "search_documents"

# The model only sees this definition. The descriptions are prompts: they decide WHEN it searches
# and HOW it writes the query (standalone, so follow-up questions work).
TOOL = {
    "type": "function",
    "function": {
        "name": NAME,
        "description": (
            "Search the user's documents (policies, standards such as ISO 27001, manuals, papers) "
            "and return the most relevant passages. Use it for any question the documents could answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "A standalone search query. Resolve words like 'it', 'that' or 'again' using the "
                        "conversation, and keep document names and clause or control numbers, "
                        "e.g. 'ISO 27001 clause 6.2 information security objectives'."
                    ),
                }
            },
            "required": ["query"],
        },
    },
}


def allowed_sources(access: Access) -> list[str] | None:
    """The indexed files this user may read (None = everything, for admins)."""
    if access.is_admin:
        return None
    return [s for s in get_store().chunk_counts() if access.can_read_document(s)]


def run_search(query: str, access: Access) -> list[dict]:
    """Blocking (Qdrant + embedding): call it with asyncio.to_thread from async code.

    Only the user's permitted files are searched, so forbidden passages never reach the model.
    """
    return get_store().search(query, k=settings.search_k, allowed=allowed_sources(access))


def format_results(results: list[dict], first_number: int) -> tuple[str, list[dict]]:
    """Numbered passages for the model, plus the same passages as source records for the UI.

    Numbers continue across tool calls (first_number), so every [n] in one answer is unique.
    """
    if not results:
        return "No relevant passages found in the documents.", []
    blocks, passages = [], []
    for number, r in enumerate(results, start=first_number):
        where = r["source"] + (f", page {r['page']}" if r.get("page") else "")
        title = f" - {r['heading']}" if r.get("heading") else ""
        blocks.append(f"[{number}] {where}{title}\n{r['text']}")
        passages.append(
            {
                "number": number,
                "source": r["source"],
                "page": r.get("page"),
                "heading": r.get("heading"),
                "snippet": r["text"][:300],
            }
        )
    return "\n\n".join(blocks), passages
