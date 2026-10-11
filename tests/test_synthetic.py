"""Unit tests on synthetic graphs for Phase 0 routing primitives.

Covers: alternative routes after closure, disconnected origins, monotonic
(shortest-path distances never decrease) after road deletion, one-way
enforcement, all-directed-edge removal for a way, and baseline
reproducibility after remove/restore.
"""
from __future__ import annotations

import random

import networkx as nx
import pytest

import routing
from routing import (
    INF,
    dist_of,
    distances_to_targets,
    graph_counts,
    is_disconnected,
    remove_way,
    restore_edges,
    way_edge_keys,
)


def two_way(G: nx.MultiDiGraph, a, b, length: float, osmid: int) -> None:
    G.add_edge(a, b, length=float(length), osmid=osmid)
    G.add_edge(b, a, length=float(length), osmid=osmid)


def diamond_graph() -> nx.MultiDiGraph:
    """Short path A-B-D (way 1) vs longer alternative A-C-D (way 2)."""
    G = nx.MultiDiGraph()
    two_way(G, "A", "B", 10, 1)
    two_way(G, "B", "D", 10, 1)
    two_way(G, "A", "C", 15, 2)
    two_way(G, "C", "D", 15, 2)
    return G


def bridge_graph() -> nx.MultiDiGraph:
    """Origin A reaches hospital H only across bridge way 9."""
    G = nx.MultiDiGraph()
    two_way(G, "A", "B", 5, 9)
    two_way(G, "B", "H", 3, 10)
    return G


def test_alternative_route_used_after_closure():
    G = diamond_graph()
    before = distances_to_targets(G, {"D"})["A"]
    assert before == pytest.approx(20.0)

    removed = remove_way(G, 1)
    assert len(removed) == 4  # both segments, both directions

    after = distances_to_targets(G, {"D"})["A"]
    assert after == pytest.approx(30.0)
    assert after > before  # detour via the alternative route


def test_disconnected_origin_after_bridge_closure():
    G = bridge_graph()
    before = distances_to_targets(G, {"H"})["A"]
    assert before == pytest.approx(8.0)

    remove_way(G, 9)
    d_after = dist_of(distances_to_targets(G, {"H"}), "A")
    assert is_disconnected(d_after)
    assert d_after == INF


def test_oneway_restrictions_respected():
    G = nx.MultiDiGraph()
    G.add_edge("S", "T", length=10.0, osmid=5)  # one-way S -> T only

    assert distances_to_targets(G, {"T"})["S"] == pytest.approx(10.0)

    # driving T -> S against the one-way must be impossible
    to_S = distances_to_targets(G, {"S"})
    assert is_disconnected(dist_of(to_S, "T"))


def test_monotonic_distances_after_random_deletions():
    """Deleting road segments may only keep or increase shortest distances."""
    rng = random.Random(42)
    n = 24
    G = nx.MultiDiGraph()
    for i in range(n):  # directed ring guarantees reachability to node 0
        G.add_edge(i, (i + 1) % n, length=5.0, osmid=1000 + i)
    chords = []
    for _ in range(40):
        u, v = rng.randrange(n), rng.randrange(n)
        if u == v:
            continue
        osmid = 5000 + len(chords)
        G.add_edge(u, v, length=float(rng.randint(2, 30)), osmid=osmid)
        chords.append(osmid)

    hospital = 0
    baseline = distances_to_targets(G, {hospital})
    assert len(baseline) == n  # everyone reachable initially

    removable = chords + [1000 + i for i in range(n)]
    rng.shuffle(removable)
    prev = baseline
    cumulative_removed: list = []
    for osmid in removable[:20]:
        removed = remove_way(G, osmid)
        assert removed, f"expected edges for way {osmid}"
        cumulative_removed.extend(removed)
        current = distances_to_targets(G, {hospital})
        for node, d_prev in prev.items():
            d_now = dist_of(current, node)
            assert d_now >= d_prev - 1e-9, (
                f"distance decreased for node {node}: {d_prev} -> {d_now}"
            )
        prev = current
    # deletions were cumulative: also verify monotonic vs original baseline
    for node, d_base in baseline.items():
        assert dist_of(prev, node) >= d_base - 1e-9
    restore_edges(G, cumulative_removed)
    assert distances_to_targets(G, {hospital}) == baseline


def test_remove_way_deletes_all_directed_and_parallel_edges():
    G = nx.MultiDiGraph()
    G.add_edge(1, 2, key="0", length=5.0, osmid=77)
    G.add_edge(2, 1, key="0", length=5.0, osmid=77)
    G.add_edge(1, 2, key="1", length=6.0, osmid=77)  # parallel edge, same way
    G.add_edge(2, 3, key="0", length=4.0, osmid=88)
    counts_before = graph_counts(G)

    keys = way_edge_keys(G, 77)
    assert len(keys) == 3

    removed = remove_way(G, 77)
    assert graph_counts(G) == (counts_before[0], counts_before[1] - 3)
    assert G.number_of_edges(1, 2) == 0
    assert G.has_edge(2, 3)

    restore_edges(G, removed)
    assert graph_counts(G) == counts_before
    restored = {(u, v, k): d for u, v, k, d in G.edges(keys=True, data=True)}
    for u, v, k, data in removed:
        assert restored[(u, v, k)] == data


def test_way_edge_keys_handles_simplified_list_osmid():
    """After OSMnx simplification one graph edge can carry several way ids."""
    G = nx.MultiDiGraph()
    G.add_edge(1, 2, length=10.0, osmid=[77, 88])
    G.add_edge(2, 3, length=10.0, osmid=99)

    assert way_edge_keys(G, 88) == [(1, 2, 0)]
    assert way_edge_keys(G, 99) == [(2, 3, 0)]
    removed = remove_way(G, 77)
    assert len(removed) == 1
    assert not G.has_edge(1, 2)
    restore_edges(G, removed)
    assert G.edges[1, 2, 0]["osmid"] == [77, 88]


def test_baseline_reproducible_after_remove_and_restore():
    G = diamond_graph()
    baseline = distances_to_targets(G, {"D"})
    counts_before = graph_counts(G)

    removed = remove_way(G, 1)  # close the SHORT A-B-D path
    during = distances_to_targets(G, {"D"})
    assert during["A"] > baseline["A"]
    assert during["A"] == pytest.approx(30.0)

    restore_edges(G, removed)
    after = distances_to_targets(G, {"D"})
    assert after == baseline
    assert graph_counts(G) == counts_before


def test_empty_targets_rejected():
    G = diamond_graph()
    with pytest.raises(ValueError):
        distances_to_targets(G, set())
