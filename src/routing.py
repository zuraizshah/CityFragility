"""Pure routing helpers shared by the analysis pipeline and unit tests.

Distances are metres (OSMnx edge "length").  One-way restrictions are
preserved by always running Dijkstra on the directed graph (or its reverse),
never on an undirected conversion.
"""
from __future__ import annotations

import math

import networkx as nx

INF = float("inf")


def distances_to_targets(
    G: nx.MultiDiGraph, target_nodes: set[int], weight: str = "length"
) -> dict[int, float]:
    """Distance in metres from every node to the nearest target node.

    Computed as a multi-source Dijkstra over the *reversed* graph, which is
    exactly the shortest drivable distance from each node to a target while
    respecting edge directions (one-ways).
    """
    if not target_nodes:
        raise ValueError("target_nodes must not be empty")
    rev = G.reverse(copy=False)
    return nx.multi_source_dijkstra_path_length(rev, list(target_nodes), weight=weight)


def dist_of(dist_map: dict[int, float], node: int) -> float:
    """Distance for a node; unreachable nodes map to +inf."""
    return dist_map.get(node, INF)


def is_disconnected(value: float) -> bool:
    return value == INF or math.isinf(value)


def way_edge_keys(G: nx.MultiDiGraph, osmid) -> list[tuple[int, int, str]]:
    """All directed edge keys (u, v, k) belonging to the given OSM way id.

    OSMnx may store a scalar or a list of way ids in the 'osmid' attribute
    after simplification; both are handled.  Both travel directions are
    included, so removing every returned edge closes the segment for good.
    """
    keys = []
    for u, v, k, data in G.edges(keys=True, data=True):
        value = data.get("osmid")
        if isinstance(value, (list, tuple, set)):
            hit = osmid in value
        else:
            hit = value == osmid
        if hit:
            keys.append((u, v, k))
    return keys


def remove_way(G: nx.MultiDiGraph, osmid) -> list[tuple[int, int, str, dict]]:
    """Delete every directed edge of `osmid`; return removed edges for restore."""
    removed = []
    for u, v, k in way_edge_keys(G, osmid):
        data = G.get_edge_data(u, v, k)
        removed.append((u, v, k, dict(data)))
        G.remove_edge(u, v, k)
    return removed


def restore_edges(G: nx.MultiDiGraph, removed: list[tuple[int, int, str, dict]]) -> None:
    """Re-insert edges previously returned by remove_way (exact keys/data)."""
    for u, v, k, data in removed:
        payload = dict(data)
        payload.pop("key", None)  # edge-data 'key' would clash with add_edge(key=...)
        G.add_edge(u, v, k, **payload)


def graph_counts(G: nx.MultiDiGraph) -> tuple[int, int]:
    return G.number_of_nodes(), G.number_of_edges()
