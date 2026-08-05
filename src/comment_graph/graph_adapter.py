"""Dependency graph over ``networkx.MultiDiGraph``.

This is the **only** module that imports networkx, so the backend can be swapped
(e.g. for rustworkx) without touching the rest of the package. All traversal the
scheduler needs is exposed here as EntityId-typed methods with deterministic
(sorted) ordering.
"""

from __future__ import annotations

import hashlib
from typing import Dict, Iterable, List

import networkx as nx

from .model import EntityId
from .edges import Edge


def _key(entity: EntityId) -> str:
    return str(entity)


class DependencyGraph:
    """Typed wrapper around a networkx MultiDiGraph of EntityId nodes."""

    def __init__(self) -> None:
        self._g: nx.MultiDiGraph = nx.MultiDiGraph()

    # -- construction -----------------------------------------------------
    def add_entity(self, entity: EntityId) -> None:
        self._g.add_node(entity)

    def add_edge(self, edge: Edge) -> None:
        self._g.add_node(edge.src)
        self._g.add_node(edge.dst)
        self._g.add_edge(edge.src, edge.dst, key=edge.relation, edge=edge)

    # -- inspection -------------------------------------------------------
    def has_node(self, entity: EntityId) -> bool:
        return self._g.has_node(entity)

    def nodes(self) -> List[EntityId]:
        return sorted(self._g.nodes, key=_key)

    def edges(self) -> List[Edge]:
        result = [data["edge"] for _, _, data in self._g.edges(data=True)]
        return sorted(result, key=lambda e: (_key(e.src), _key(e.dst), e.relation.value))

    def in_edges(self, entity: EntityId) -> List[Edge]:
        if not self._g.has_node(entity):
            return []
        result = [data["edge"] for _, _, data in self._g.in_edges(entity, data=True)]
        return sorted(result, key=lambda e: (_key(e.src), e.relation.value))

    def out_edges(self, entity: EntityId) -> List[Edge]:
        if not self._g.has_node(entity):
            return []
        result = [data["edge"] for _, _, data in self._g.out_edges(entity, data=True)]
        return sorted(result, key=lambda e: (_key(e.dst), e.relation.value))

    def predecessors(self, entity: EntityId) -> List[EntityId]:
        if not self._g.has_node(entity):
            return []
        return sorted(set(self._g.predecessors(entity)), key=_key)

    def successors(self, entity: EntityId) -> List[EntityId]:
        if not self._g.has_node(entity):
            return []
        return sorted(set(self._g.successors(entity)), key=_key)

    # -- structure --------------------------------------------------------
    def sccs(self) -> List[List[EntityId]]:
        """Strongly connected components, each sorted, ordered by first member."""
        comps = [sorted(c, key=_key) for c in nx.strongly_connected_components(self._g)]
        return sorted(comps, key=lambda c: _key(c[0]))

    def topo_components(self) -> List[List[EntityId]]:
        """SCC-condensed components in a deterministic topological order.

        Cyclic components appear as multi-node lists; acyclic nodes as
        singletons. Ties within the topological order are broken lexically so
        the schedule is reproducible.
        """
        condensation = nx.condensation(self._g)
        members: Dict[int, List[EntityId]] = {
            n: sorted(condensation.nodes[n]["members"], key=_key)
            for n in condensation.nodes
        }
        order = nx.lexicographical_topological_sort(
            condensation, key=lambda n: _key(members[n][0])
        )
        return [members[n] for n in order]

    def digest(self) -> str:
        """Stable SHA-256 over the node set and typed edge set.

        Independent of insertion order; sensitive to nodes, edge endpoints, and
        relation type so stale-memory checks can detect a changed graph.
        """
        node_part = sorted(_key(n) for n in self._g.nodes)
        edge_part = sorted(
            f"{_key(u)}|{_key(v)}|{k.value}" for u, v, k in self._g.edges(keys=True)
        )
        payload = "\n".join(node_part) + "\n--\n" + "\n".join(edge_part)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
