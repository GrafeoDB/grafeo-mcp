"""Output budget: large results stay valid JSON.

``_truncate`` used to cut the serialized text at 8,000 characters and append a
note, which left invalid JSON for any large algorithm, search or batch result.
"""

from __future__ import annotations

import json
import random
from typing import Any

import grafeo
import pytest

from grafeo_mcp.tools._helpers import _MAX_RESULT_CHARS, _truncate
from grafeo_mcp.tools.algorithms import betweenness_centrality, connected_components, louvain, pagerank
from grafeo_mcp.tools.search import search_text
from grafeo_mcp.tools.vector import vector_graph_search, vector_search
from tests.conftest import _make_ctx


def _check(text: str, limit: int = _MAX_RESULT_CHARS) -> Any:
    assert len(text) <= limit, len(text)
    return json.loads(text)


class TestTruncateHelper:
    def test_small_payload_unchanged(self):
        assert _truncate({"a": [1, 2]}) == '{"a":[1,2]}'
        assert _truncate([1, 2]) == "[1,2]"

    def test_long_list_is_wrapped(self):
        payload = [{"node_id": i, "text": "x" * 50} for i in range(500)]
        result = _check(_truncate(payload))
        assert result["truncated"] is True
        kept = len(result["results"])
        assert 0 < kept < 500
        assert result["omitted"] == {"results": 500 - kept}
        assert result["results"][0] == payload[0]

    def test_dict_keeps_scalars(self):
        payload = {
            "algorithm": "pagerank",
            "total_nodes_scored": 900,
            "results": [{"id": i, "s": "y" * 40} for i in range(900)],
        }
        result = _check(_truncate(payload))
        assert (result["algorithm"], result["total_nodes_scored"]) == ("pagerank", 900)
        assert result["omitted"]["results"] == 900 - len(result["results"])

    def test_many_small_groups(self):
        payload = {"communities": {str(i): [{"node_id": i, "name": "n" * 20}] for i in range(3000)}}
        result = _check(_truncate(payload))
        assert result["omitted"] == {"communities": 3000 - len(result["communities"])}

    def test_one_huge_group_is_cut_inside(self):
        payload = {"communities": {"0": [{"node_id": i, "name": "n" * 20} for i in range(3000)], "1": [{"node_id": 1}]}}
        result = _check(_truncate(payload))
        assert 0 < len(result["communities"]["0"]) < 3000
        assert "communities.0" in result["omitted"]

    def test_long_strings_are_shortened_with_their_length(self):
        result = _check(_truncate({"data": "x" * 50_000}))
        assert result["data"].endswith("... [50000 chars]")
        assert result["truncated"] is True

    def test_huge_record_keeps_its_keys(self):
        payload = [{"node_id": i, "properties": {"content": "c" * 20_000, "title": f"t{i}"}} for i in range(4)]
        result = _check(_truncate(payload))
        first = result["results"][0]
        assert first["node_id"] == 0
        assert first["properties"]["title"] == "t0"
        assert first["properties"]["content"].endswith("... [20000 chars]")

    def test_tiny_budget_falls_back_to_a_note(self):
        result = _check(_truncate({"data": "x" * 1000}, limit=100), limit=100)
        assert result["truncated"] is True and "note" in result

    @pytest.mark.parametrize("seed", range(20))
    def test_random_payloads_stay_valid(self, seed):
        rng = random.Random(seed)

        def value(depth: int):
            kind = rng.choice(["str", "int", "list", "dict"] if depth < 3 else ["str", "int"])
            if kind == "str":
                return "s" * rng.randint(0, 3000)
            if kind == "int":
                return rng.randint(0, 10**9)
            if kind == "list":
                return [value(depth + 1) for _ in range(rng.randint(0, 60))]
            return {f"k{i}": value(depth + 1) for i in range(rng.randint(0, 30))}

        payload = {f"top{i}": value(0) for i in range(rng.randint(1, 6))}
        _check(_truncate(payload))


# ---------------------------------------------------------------------------
# Tools with large outputs
# ---------------------------------------------------------------------------


@pytest.fixture()
def big_ctx():
    db = grafeo.GrafeoDB()
    names = ["node-" + "n" * 60 + str(i) for i in range(600)]
    ids = [db.create_node(["Item"], {"name": name}).id for name in names]
    for i in range(0, 300, 2):
        db.create_edge(ids[i], ids[i + 1], "PAIR")
    yield _make_ctx(db)
    db.close()


class TestToolsStayValid:
    def test_louvain(self, big_ctx):
        result = _check(louvain(ctx=big_ctx))
        assert result["truncated"] is True
        assert result["num_communities"] == 450  # 150 pairs + 300 isolated nodes, reported in full

    def test_pagerank_large_top_k(self, big_ctx):
        result = _check(pagerank(top_k=600, ctx=big_ctx))
        assert result["total_nodes_scored"] == 600
        assert result["truncated"] is True

    def test_betweenness_large_top_k(self, big_ctx):
        result = _check(betweenness_centrality(top_k=600, ctx=big_ctx))
        assert result["truncated"] is True

    def test_connected_components(self, big_ctx):
        result = _check(connected_components(ctx=big_ctx))
        assert result["num_components"] == 450

    def test_search_results_with_long_text(self):
        db = grafeo.GrafeoDB()
        try:
            for i in range(10):
                db.create_node(
                    ["Doc"], {"body": f"graph database chapter {i} " + "lorem ipsum " * 1000, "emb": [1.0, float(i)]}
                )
            db.create_text_index("Doc", "body")
            db.create_vector_index("Doc", "emb", 2, "cosine")
            ctx = _make_ctx(db)
            text_hits = _check(search_text("Doc", "body", "graph", limit=10, ctx=ctx))
            assert text_hits["truncated"] is True
            vector_hits = _check(vector_search("Doc", "emb", [1.0, 0.0], k=10, ctx=ctx))
            assert vector_hits["truncated"] is True
            assert vector_hits["results"][0]["properties"]["body"].startswith("graph database chapter")
            _check(vector_graph_search("Doc", "emb", [1.0, 0.0], k=10, ctx=ctx))
        finally:
            db.close()
