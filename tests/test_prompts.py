"""Tests for prompts/templates.py — verify prompts return well-formed guidance."""

from __future__ import annotations

import re

import pytest

from grafeo_mcp.prompts.templates import (
    explore_graph,
    graph_analysis,
    knowledge_extraction,
    similarity_search,
)


class TestExploreGraph:
    def test_default(self):
        result = explore_graph()
        assert "graph_info" in result
        assert "search_nodes_by_label" in result
        assert "get_neighbors" in result
        assert "execute_gql" in result
        assert "Step 1" in result

    def test_with_focus_label(self):
        result = explore_graph(focus_label="Person")
        assert "Person" in result
        assert "Focus" in result


class TestKnowledgeExtraction:
    def test_basic(self):
        result = knowledge_extraction(text="Alice works at Acme Corp.")
        assert "create_node" in result
        assert "create_edge" in result
        assert "get_neighbors" in result
        assert "Alice works at Acme Corp." in result


class TestGraphAnalysis:
    def test_default(self):
        result = graph_analysis()
        assert "louvain" in result
        assert "pagerank" in result
        assert "get_neighbors" in result

    def test_custom_top_k(self):
        result = graph_analysis(top_k=5)
        assert "top_k=5" in result


class TestSimilaritySearch:
    def test_default(self):
        result = similarity_search()
        assert "vector_search" in result
        assert "vector_graph_search" in result
        assert "get_neighbors" in result

    def test_with_label(self):
        result = similarity_search(label="Document", property="embedding")
        assert "Document" in result
        assert "embedding" in result

    def test_with_description(self):
        result = similarity_search(description="machine learning papers")
        assert "machine learning papers" in result


# ---------------------------------------------------------------------------
# T15: All 4 prompts render without errors
# ---------------------------------------------------------------------------

_ALL_PROMPTS = [
    pytest.param(lambda: explore_graph(), id="explore_graph"),
    pytest.param(lambda: explore_graph(focus_label="Person"), id="explore_graph_focus"),
    pytest.param(lambda: knowledge_extraction(text="Test text."), id="knowledge_extraction"),
    pytest.param(lambda: graph_analysis(), id="graph_analysis"),
    pytest.param(lambda: graph_analysis(top_k=5), id="graph_analysis_top_k"),
    pytest.param(lambda: similarity_search(), id="similarity_search"),
    pytest.param(lambda: similarity_search(label="Doc", property="emb"), id="similarity_search_label"),
    pytest.param(lambda: similarity_search(description="test query"), id="similarity_search_desc"),
]

# Regex to detect unresolved single-brace template placeholders like {variable_name}.
# Excludes patterns that look like JSON keys/values, GQL code, or example code
# by only matching lowercase identifiers with underscores (typical placeholder names).
_PLACEHOLDER_RE = re.compile(r"(?<!\{)\{[a-z_]+\}(?!\})")

# Known non-placeholder patterns that appear in prompt example code and are legitimate.
_KNOWN_SAFE = frozenset()


class TestAllPromptsRender:
    @pytest.mark.parametrize("render", _ALL_PROMPTS)
    def test_renders_non_empty_string(self, render):
        result = render()
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.parametrize("render", _ALL_PROMPTS)
    def test_no_unresolved_placeholders(self, render):
        result = render()
        # Check that no raw template placeholders like {{variable}} remain
        assert "{{" not in result
        assert "}}" not in result
        # Check for unresolved single-brace placeholders like {variable_name}.
        # Filter out known safe patterns that appear in example code.
        matches = _PLACEHOLDER_RE.findall(result)
        unresolved = [m for m in matches if m not in _KNOWN_SAFE]
        assert unresolved == [], f"Unresolved template placeholders found: {unresolved}"
