"""Tests for prompts/templates.py — verify prompts return well-formed guidance."""

from __future__ import annotations

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
