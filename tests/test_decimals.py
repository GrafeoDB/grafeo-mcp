"""Exact decimals in tool output.

grafeo 0.6 reads a GQL number with a point (``1.50``, ``0.1 + 0.2``) and a
DECIMAL property as ``decimal.Decimal``. Tools must write them as JSON numbers
that keep their digits: not as strings (``json.dumps(default=str)`` did that)
and not rounded through a float.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from typing import Any

import pytest
from mcp.types import TextContent

from grafeo_mcp.server import mcp
from grafeo_mcp.tools._helpers import _truncate, to_json
from grafeo_mcp.tools.algorithms import dijkstra
from grafeo_mcp.tools.graph import get_neighbors, get_node, search_nodes_by_label
from grafeo_mcp.tools.query import execute_gql
from tests.conftest import client_session


def _exact(text: str) -> Any:
    """Parse tool output keeping every number's digits."""
    return json.loads(text, parse_float=Decimal)


def _as_exact(value: Any) -> Any:
    """What a float or Decimal from the engine reads as in exact JSON."""
    return Decimal(str(value)) if isinstance(value, float | Decimal) else value


# ---------------------------------------------------------------------------
# to_json and truncation
# ---------------------------------------------------------------------------


class TestToJson:
    def test_decimal_is_a_number_with_its_digits(self):
        assert to_json({"price": Decimal("1.50")}) == '{"price": 1.50}'
        assert to_json([Decimal("0.3"), Decimal("-2.125")], compact=True) == "[0.3,-2.125]"

    def test_nested_decimals(self):
        text = to_json({"rows": [{"n": {"_id": 1, "price": Decimal("9.99")}, "l": [Decimal("1.5"), 2]}]})
        assert _exact(text) == {"rows": [{"n": {"_id": 1, "price": Decimal("9.99")}, "l": [Decimal("1.5"), 2]}]}
        assert "9.99" in text and '"9.99"' not in text

    def test_large_and_exponent_decimals_stay_valid_json(self):
        big = Decimal("12345678901234567890.123456789012345678")
        assert _exact(to_json({"x": big}))["x"] == big, "38 digits survive (a float keeps about 17)"
        assert json.loads(to_json({"x": Decimal("1E+2")}))["x"] == 100

    def test_non_finite_decimals_and_other_values_become_text(self):
        assert json.loads(to_json({"x": Decimal("NaN")})) == {"x": "NaN"}
        assert json.loads(to_json({"d": datetime.date(2026, 10, 20)})) == {"d": "2026-10-20"}

    def test_strings_are_never_turned_into_numbers(self):
        text = to_json({"s": "1.50", "t": "\x00grafeo-mcp-decimal-0:1.5"})
        assert json.loads(text) == {"s": "1.50", "t": "\x00grafeo-mcp-decimal-0:1.5"}

    def test_truncation_keeps_decimals_exact(self):
        payload = {"results": [{"i": i, "price": Decimal("1.50"), "pad": "x" * 50} for i in range(500)]}
        text = _truncate(payload, limit=2_000)
        assert len(text) <= 2_000
        parsed = _exact(text)
        assert parsed["truncated"] is True
        assert parsed["results"][0]["price"] == Decimal("1.50")
        assert '"price":1.50' in text, "the decimal keeps its scale through the cut"


# ---------------------------------------------------------------------------
# Tools on engine values
# ---------------------------------------------------------------------------


class TestToolOutput:
    def test_execute_gql_numbers_with_a_point(self, ctx):
        db = ctx.request_context.lifespan_context.db
        query = "RETURN 1.50 AS a, 0.1 + 0.2 AS b, 1.5e0 AS c, $d AS d, [2.5, 1] AS l, {p: 0.25} AS m"
        params = {"d": Decimal("2.25")}
        engine_row = next(iter(db.execute(query, params)))
        result = _exact(execute_gql(query, params=params, ctx=ctx))
        row = result["rows"][0]
        assert row["a"] == _as_exact(engine_row["a"]) and row["b"] == _as_exact(engine_row["b"])
        assert row["c"] == Decimal("1.5") and row["d"] == Decimal("2.25")
        assert row["l"] == [_as_exact(engine_row["l"][0]), 1] and row["m"] == {"p": _as_exact(engine_row["m"]["p"])}
        assert str(row["a"]) == "1.50" and row["b"] == Decimal("0.3")

    def test_node_tools_with_a_decimal_property(self, ctx):
        db = ctx.request_context.lifespan_context.db
        node = db.create_node(["Item"], {"price": Decimal("9.99"), "name": "pen"})
        other = db.create_node(["Item"], {"name": "cap"})
        db.create_edge(node.id, other.id, "FITS", {"w": Decimal("0.5")})
        stored = db.get_node(node.id).properties()["price"]

        assert _exact(get_node(node.id, ctx=ctx))["properties"]["price"] == _as_exact(stored)
        page = _exact(search_nodes_by_label("Item", ctx=ctx))
        assert page["results"][0]["properties"]["price"] == _as_exact(stored)
        around = _exact(get_neighbors(other.id, ctx=ctx))
        assert around["neighbors"][0]["properties"]["price"] == _as_exact(stored)

    def test_dijkstra_reads_decimal_weights(self, ctx):
        # grafeo 0.6.2 reads a decimal weight's value, so the cheap path through
        # the decimals wins over the direct edge with weight 10.
        db = ctx.request_context.lifespan_context.db
        db.execute("INSERT (:P {n: 'a'})-[:R {w: 2.5}]->(:P {n: 'b'})-[:R {w: 0.5}]->(:P {n: 'c'})")
        db.execute("MATCH (a:P {n: 'a'}), (c:P {n: 'c'}) INSERT (a)-[:R {w: 10}]->(c)")
        result = dijkstra(0, 2, weight_property="w", ctx=ctx)
        parsed = json.loads(result)
        assert parsed["distance"] == 3.0 and [n["node_id"] for n in parsed["path"]] == [0, 1, 2]

    def test_dijkstra_without_weights_ignores_decimals(self, ctx):
        db = ctx.request_context.lifespan_context.db
        db.execute("INSERT (:P)-[:R {w: 2.5}]->(:P)")
        assert json.loads(dijkstra(0, 1, ctx=ctx))["distance"] == 1.0

    def test_dijkstra_weight_property_is_not_query_text(self, ctx):
        db = ctx.request_context.lifespan_context.db
        db.execute("INSERT (:P)-[:R {w: 2}]->(:P)")
        injected = "w` IS NOT NULL DETACH DELETE r WITH r MATCH ()-[r]->() WHERE r.`w"
        result = dijkstra(0, 1, weight_property=injected, ctx=ctx)
        assert db.edge_count == 1, result
        assert json.loads(result)["distance"] == 1.0, "an unknown weight property counts every edge as 1.0"


# ---------------------------------------------------------------------------
# Over MCP
# ---------------------------------------------------------------------------


@pytest.fixture()
def _in_memory(monkeypatch):
    monkeypatch.delenv("GRAFEO_DB_PATH", raising=False)
    monkeypatch.delenv("GRAFEO_READ_ONLY", raising=False)


@pytest.mark.usefixtures("_in_memory")
async def test_decimals_over_mcp_are_json_numbers():
    async with client_session(mcp) as client:
        await client.call_tool("execute_gql", {"query": "INSERT (:Item {price: 1.50})"})
        result = await client.call_tool("execute_gql", {"query": "MATCH (i:Item) RETURN i.price AS p, i"})
        assert result.is_error is False
        content = result.content[0]
        assert isinstance(content, TextContent)
        rows = _exact(content.text)["rows"]
        assert rows[0]["p"] == Decimal("1.5") and rows[0]["i"]["price"] == Decimal("1.5")
        assert not isinstance(json.loads(content.text)["rows"][0]["p"], str)
