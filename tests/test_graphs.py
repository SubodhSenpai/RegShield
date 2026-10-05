"""The graph algorithms: cycle detection in a directed graph, and repeated cycles in a walk."""

import pytest

from regression_shield.core.graphs import find_cycle, walk_cycles


@pytest.mark.parametrize("edges", [
    [],
    [("a", "b")],
    [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")],  # a diamond: two paths, no cycle
    [("a", "b"), ("x", "b"), ("b", "c")],
])
def test_a_dag_has_no_cycle(edges):
    assert find_cycle(edges) is None


@pytest.mark.parametrize("edges, cycle", [
    ([("a", "b"), ("b", "a")], ["a", "b", "a"]),
    ([("a", "b"), ("b", "c"), ("c", "a")], ["a", "b", "c", "a"]),
    ([("a", "a")], ["a", "a"]),
    ([("x", "y"), ("a", "b"), ("b", "c"), ("c", "b")], ["b", "c", "b"]),  # not reachable from the first node
    ([("start", "a"), ("a", "b"), ("b", "a"), ("b", "end")], ["a", "b", "a"]),
])
def test_a_cycle_is_reported_as_its_path(edges, cycle):
    assert find_cycle(edges) == cycle


def test_the_same_edges_always_report_the_same_cycle():
    edges = [("a", "b"), ("b", "c"), ("c", "a"), ("c", "d"), ("d", "b")]
    assert find_cycle(edges) == find_cycle(list(edges)) == ["a", "b", "c", "a"]


def test_long_chains_need_no_recursion():
    chain = [(n, n + 1) for n in range(50_000)]
    assert find_cycle(chain) is None
    assert len(find_cycle([*chain, (50_000, 0)])) == 50_002


@pytest.mark.parametrize("walk, cycles", [
    ("abcabca", {("a", "b", "c"): 2}),
    ("xbcabcab", {("a", "b", "c"): 2}),           # entered at b: the same cycle
    ("abcacba", {("a", "b", "c"): 1, ("a", "c", "b"): 1}),  # the two directions differ
    ("ababa", {("a", "b"): 2}),
    ("abcba", {("b", "c"): 1, ("a", "b"): 1}),      # a loop inside a loop
    ("aab", {}),                                    # staying on a node isn't a cycle
    ("abcd", {}),
    ("", {}),
])
def test_walk_cycles(walk, cycles):
    assert walk_cycles(walk) == cycles


def test_walk_cycles_takes_any_hashable_nodes():
    assert walk_cycles([1, 2, 1, 2, 1]) == {(1, 2): 2}
