"""Graph algorithms behind the ordering and multi-agent checks.

- ``find_cycle``: depth-first search with three colours, O(nodes + edges). Run when a
  scenario is built, so ordering rules that contradict each other (a before b, b
  before a) are rejected instead of failing every trace.
- ``walk_cycles``: chronological loop erasure over a walk, such as the agents that
  control passes through. When the walk comes back to a node already on its current
  path, the loop it closed is cut out and counted. One pass finds repeated cycles
  of any length.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Iterable, Iterator
from typing import TypeVar

Node = TypeVar("Node", bound=Hashable)

_UNSEEN, _ON_PATH, _DONE = 0, 1, 2


def find_cycle(edges: Iterable[tuple[Node, Node]]) -> list[Node] | None:
    """A cycle in the directed graph ``edges`` as ``[a, b, ..., a]``, or None when it's a DAG.

    Iterative, so long chains don't hit the recursion limit. Nodes are visited in the
    order they first appear, so the same edges always report the same cycle.
    """
    graph: dict[Node, list[Node]] = {}
    for before, after in edges:
        graph.setdefault(before, []).append(after)
        graph.setdefault(after, [])

    state = dict.fromkeys(graph, _UNSEEN)
    for root in graph:
        if state[root] != _UNSEEN:
            continue
        state[root] = _ON_PATH
        path = [root]
        pending: list[Iterator[Node]] = [iter(graph[root])]
        while pending:
            for nxt in pending[-1]:
                if state[nxt] == _ON_PATH:  # an edge back into the current path closes a cycle
                    return [*path[path.index(nxt):], nxt]
                if state[nxt] == _UNSEEN:
                    state[nxt] = _ON_PATH
                    path.append(nxt)
                    pending.append(iter(graph[nxt]))
                    break
            else:  # every edge out of this node explored
                state[path.pop()] = _DONE
                pending.pop()
    return None


def walk_cycles(walk: Iterable[Node]) -> Counter[tuple[Node, ...]]:
    """The cycles a walk closed, with how often each was closed.

    A cycle is keyed by its rotation that starts at its smallest node, so a loop counts
    as the same cycle wherever the walk entered it; ``a -> b -> c -> a`` and
    ``a -> c -> b -> a`` stay different. Staying on a node isn't a cycle.
    """
    path: list[Node] = []
    position: dict[Node, int] = {}
    cycles: Counter[tuple[Node, ...]] = Counter()
    for node in walk:
        start = position.get(node)
        if start is None:
            position[node] = len(path)
            path.append(node)
            continue
        loop = path[start:]
        for erased in path[start + 1:]:
            del position[erased]
        del path[start + 1:]
        if len(loop) > 1:
            first = loop.index(min(loop, key=repr))  # repr: nodes needn't be comparable
            cycles[tuple(loop[first:] + loop[:first])] += 1
    return cycles
