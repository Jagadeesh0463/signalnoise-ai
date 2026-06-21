"""
src/graph/knowledge_graph.py

Knowledge Graph — builds a NetworkX graph connecting roles, teams,
signals, and documents. Used in Sprint 2 to surface cross-team risks.

Pipeline position:
    Detector → KnowledgeGraph (enriches Signal with related_teams)
    Dashboard → KnowledgeGraph (renders connections)

What it tracks:
    - Role nodes:    "[Person-A]", "[Person-B]"
    - Team nodes:    "Backend-Team", "Platform-Team"
    - Signal nodes:  signal IDs
    - Document nodes: document IDs
    - Edges:         role→team, signal→role, signal→document

Design rules:
    - Only anonymized role codes ever enter this graph — no real names
    - Graph is rebuilt on each pipeline run (MVP) — persisted to disk as JSON
    - Sprint 2 will add graph queries for cross-team risk detection

Usage:
    from src.graph.knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph()
    kg.add_signal(signal, anon_doc)
    teams = kg.get_teams_for_signal(signal.id)
"""

import json
import logging
import re
from pathlib import Path

import networkx as nx

from src.config import config
from src.exceptions import SignalNoiseError
from src.models import AnonymizedDocument, Signal

logger = logging.getLogger(__name__)

# Path where the graph is saved between runs
GRAPH_SAVE_PATH = Path("data/processed/knowledge_graph.json")

# Regex to extract role codes like [Person-A], [Backend-Lead-B] from anonymized text
ROLE_CODE_PATTERN = re.compile(r"\[([A-Za-z][A-Za-z0-9\-]+)\]")


class KnowledgeGraph:
    """
    NetworkX-backed knowledge graph for SignalNoise AI.

    Node types:
        - role:     anonymized role code e.g. "[Person-A]"
        - team:     team name e.g. "Backend-Team"
        - signal:   signal ID
        - document: document ID

    Edge types:
        - role → team:     role belongs to a team (inferred from signal context)
        - signal → role:   this signal involves this role
        - signal → document: this signal came from this document
    """

    def __init__(self) -> None:
        self.graph = nx.DiGraph()
        logger.info("KnowledgeGraph initialized — empty graph.")

    # ── Building the graph ────────────────────────────────────────────────────

    def add_signal(self, signal: Signal, anon_doc: AnonymizedDocument) -> None:
        """
        Add a signal and its related roles/documents to the graph.

        Extracts role codes from the anonymized document text and
        connects them to the signal node.

        Args:
            signal:   A Signal object from the Detector.
            anon_doc: The AnonymizedDocument the signal came from.
        """
        # Add signal node
        self.graph.add_node(
            signal.id,
            node_type="signal",
            title=signal.title,
            severity=signal.severity,
            category=signal.category,
        )

        # Add document node and connect to signal
        self.graph.add_node(
            anon_doc.document_id,
            node_type="document",
            filename="anonymized",
        )
        self.graph.add_edge(signal.id, anon_doc.document_id, edge_type="came_from")

        # Extract role codes from anonymized text
        role_codes = ROLE_CODE_PATTERN.findall(anon_doc.anonymized_text)
        unique_roles = set(role_codes)

        for role_code in unique_roles:
            full_code = f"[{role_code}]"

            # Add role node
            self.graph.add_node(full_code, node_type="role", code=role_code)

            # Connect signal → role
            self.graph.add_edge(signal.id, full_code, edge_type="involves_role")

            # Infer team from role code and connect role → team
            team = _infer_team(role_code)
            if team:
                self.graph.add_node(team, node_type="team")
                self.graph.add_edge(full_code, team, edge_type="belongs_to_team")

        # Update Signal's related_teams list
        signal.related_teams = self.get_teams_for_signal(signal.id)

        logger.info(
            "Graph updated — signal=%s, roles=%d, teams=%s",
            signal.id[:8],
            len(unique_roles),
            signal.related_teams,
        )

    def add_document(self, anon_doc: AnonymizedDocument) -> None:
        """
        Add a document node and all its role codes to the graph
        without linking to a specific signal.
        Used to pre-populate the graph before signal detection runs.
        """
        self.graph.add_node(
            anon_doc.document_id,
            node_type="document",
        )

        role_codes = ROLE_CODE_PATTERN.findall(anon_doc.anonymized_text)
        for role_code in set(role_codes):
            full_code = f"[{role_code}]"
            self.graph.add_node(full_code, node_type="role", code=role_code)
            self.graph.add_edge(anon_doc.document_id, full_code, edge_type="mentions_role")

            team = _infer_team(role_code)
            if team:
                self.graph.add_node(team, node_type="team")
                self.graph.add_edge(full_code, team, edge_type="belongs_to_team")

    # ── Querying the graph ────────────────────────────────────────────────────

    def get_teams_for_signal(self, signal_id: str) -> list[str]:
        """
        Return all teams connected to a signal (via role codes).
        Used to populate Signal.related_teams.
        """
        teams: list[str] = []
        if signal_id not in self.graph:
            return teams

        # Signal → role → team (two hops)
        for role_node in self.graph.successors(signal_id):
            if self.graph.nodes[role_node].get("node_type") == "role":
                for team_node in self.graph.successors(role_node):
                    if self.graph.nodes[team_node].get("node_type") == "team":
                        if team_node not in teams:
                            teams.append(team_node)
        return teams

    def get_roles_for_signal(self, signal_id: str) -> list[str]:
        """Return all role codes connected to a signal."""
        return [
            node for node in self.graph.successors(signal_id)
            if self.graph.nodes[node].get("node_type") == "role"
        ]

    def get_signals_for_team(self, team: str) -> list[str]:
        """Return all signal IDs that involve a given team."""
        signal_ids: list[str] = []
        if team not in self.graph:
            return signal_ids

        # Walk backwards: team ← role ← signal
        for role_node in self.graph.predecessors(team):
            if self.graph.nodes[role_node].get("node_type") == "role":
                for signal_node in self.graph.predecessors(role_node):
                    if self.graph.nodes[signal_node].get("node_type") == "signal":
                        if signal_node not in signal_ids:
                            signal_ids.append(signal_node)
        return signal_ids

    def get_all_teams(self) -> list[str]:
        """Return all team nodes in the graph."""
        return [
            n for n, d in self.graph.nodes(data=True)
            if d.get("node_type") == "team"
        ]

    def get_all_signals(self) -> list[str]:
        """Return all signal node IDs in the graph."""
        return [
            n for n, d in self.graph.nodes(data=True)
            if d.get("node_type") == "signal"
        ]

    def summary(self) -> dict:
        """Return a summary of the graph for logging and dashboard display."""
        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "signals": len(self.get_all_signals()),
            "teams": len(self.get_all_teams()),
            "roles": len([
                n for n, d in self.graph.nodes(data=True)
                if d.get("node_type") == "role"
            ]),
            "documents": len([
                n for n, d in self.graph.nodes(data=True)
                if d.get("node_type") == "document"
            ]),
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: Path | None = None) -> None:
        """Save the graph to disk as JSON (node-link format)."""
        save_path = path or GRAPH_SAVE_PATH
        save_path.parent.mkdir(parents=True, exist_ok=True)
        data = nx.node_link_data(self.graph)
        save_path.write_text(json.dumps(data, indent=2))
        logger.info("Knowledge graph saved to: %s", save_path)

    def load(self, path: Path | None = None) -> None:
        """Load a previously saved graph from disk."""
        load_path = path or GRAPH_SAVE_PATH
        if not load_path.exists():
            logger.warning("No saved graph found at %s — starting fresh.", load_path)
            return
        data = json.loads(load_path.read_text())
        self.graph = nx.node_link_graph(data)
        logger.info(
            "Knowledge graph loaded — %d nodes, %d edges.",
            self.graph.number_of_nodes(),
            self.graph.number_of_edges(),
        )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _infer_team(role_code: str) -> str | None:
    """
    Infer a team name from a role code.
    Role codes follow the pattern: [Type-Letter] e.g. [Person-A], [Backend-Lead-A]

    For MVP: map known role prefixes to teams.
    In Sprint 2: this will be driven by org chart data.
    """
    role_lower = role_code.lower()

    if "backend" in role_lower:
        return "Backend-Team"
    if "platform" in role_lower:
        return "Platform-Team"
    if "sre" in role_lower or "ops" in role_lower:
        return "Operations-Team"
    if "frontend" in role_lower or "ui" in role_lower:
        return "Frontend-Team"
    if "data" in role_lower:
        return "Data-Team"
    if "product" in role_lower or "pm" in role_lower:
        return "Product-Team"
    if "programme" in role_lower or "delivery" in role_lower:
        return "Delivery-Team"

    # Generic Person-A, Person-B etc — cannot infer team without org chart
    return None
