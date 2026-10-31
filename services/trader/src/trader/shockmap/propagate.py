"""Shock propagation map: DAG traversal to compute per-ticker exposures."""
from __future__ import annotations
from trader.settings import get_shockmap

def load_graph() -> dict:
    sm = get_shockmap()
    nodes = {n["id"]: n for n in sm["nodes"]}
    edges = sm["edges"]
    adj: dict[str, list[dict]] = {}
    for e in edges:
        adj.setdefault(e["from"], []).append(e)
    return {"nodes": nodes, "edges": edges, "adj": adj}

def propagate(events: list[dict], max_depth: int = 3, damping: float = 0.7, half_life_days: float = 10) -> dict:
    """events: [{node_id, direction, magnitude, confidence}]. Returns {ticker: exposure}."""
    g = load_graph()
    adj = g["adj"]
    exposure: dict[str, float] = {}
    explanations: dict[str, list[str]] = {}

    for ev in events:
        node = ev["node_id"]
        s0 = ev["direction"] * ev["magnitude"] * ev.get("confidence", 0.5)
        visited: dict[str, float] = {node: s0}
        explanations.setdefault(node, [])
        queue: list[tuple[str, float, list[str]]] = [(node, s0, [node])]
        while queue:
            cur, shock, path = queue.pop(0)
            for edge in adj.get(cur, []):
                child = edge["to"]
                child_shock = shock * edge["weight"] * damping
                if abs(child_shock) < 0.001:
                    continue
                visited[child] = visited.get(child, 0) + child_shock
                if len(path) < max_depth:
                    queue.append((child, child_shock, path + [child]))
        for node_id, shock in visited.items():
            if g["nodes"].get(node_id, {}).get("type") == "ticker":
                exposure[node_id] = exposure.get(node_id, 0) + shock
                explanations.setdefault(node_id, []).append(f"{shock:.3f} ← {' ← '.join(path)}")
    return {"exposure": exposure, "explanations": explanations}
