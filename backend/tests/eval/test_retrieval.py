"""Search quality, without the language model: is the right passage in the top results?"""

import pytest

from tests.eval.helpers import params

pytestmark = [pytest.mark.eval, pytest.mark.retrieval]


@pytest.mark.parametrize("case", params("retrieval"))
def test_search(case, admin, record_property):
    hits = admin.get("/api/documents/search", params={"q": case["question"], "k": 5}).json()

    if case.get("expect_nothing"):
        assert hits == [], f"expected no passages, got {[(h['source'], h['page'], h['similarity']) for h in hits]}"
        return

    want = case["expect"]
    rank = next(
        (i for i, h in enumerate(hits, 1) if h["source"] == want["source"] and want.get("page") in (None, h["page"])),
        0,  # 0 = not in the results
    )
    record_property("rank", rank)
    within = case.get("within", 3)
    assert 0 < rank <= within, f"expected {want} in the top {within}, got {[(h['source'], h['page']) for h in hits]}"
