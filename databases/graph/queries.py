"""
TransitFlow — Neo4j Graph Database Layer
=========================================
This module handles all queries to Neo4j.

GRAPH ROLE:
  - Model the dual transit network (city metro M1–M4 + national rail NR1–NR2)
  - Find fastest routes (Dijkstra by travel_time_min via APOC)
  - Find cheapest routes (Dijkstra by fare via APOC)
  - Find alternative routes avoiding a given station
  - Find cross-network interchange paths (metro → rail or rail → metro)
  - Show delay ripple: which stations are affected within N hops

STUDENT TASK
------------
Design your graph schema (node labels, relationship types, properties)
based on the data in train-mock-data/, seed it with skeleton/seed_neo4j.py,
then implement the query_ functions below.

Functions prefixed with `query_` are called by the agent (skeleton/agent.py).
"""

from __future__ import annotations

from typing import Optional

from neo4j import GraphDatabase

from skeleton.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD


def _driver():
    """Return a Neo4j driver. Caller is responsible for closing."""
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


# ── Example ───────────────────────────────────────────────────────────────────
# The block below shows the query pattern: open a session, run Cypher, return data.

def example_count_nodes() -> int:
    """Example: count all nodes currently in the graph."""
    with _driver() as driver:
        with driver.session() as session:
            result = session.run("MATCH (n) RETURN count(n) AS total")
            return result.single()["total"]

# ── FASTEST ROUTE (Dijkstra by travel_time_min) ───────────────────────────────

def query_shortest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
) -> dict:
    """
    Find the fastest path between two stations, minimising total travel time.
    """
    with _driver() as driver:
        with driver.session() as session:
            cypher = """
                MATCH (start {station_id: $origin_id})
                MATCH (end {station_id: $destination_id})
                CALL apoc.algo.dijkstra(start, end, 'METRO_LINK|RAIL_LINK|INTERCHANGE_TO', 'travel_time_min')
                YIELD path, weight
                RETURN path, weight
            """
            try:
                result = session.run(cypher, origin_id=origin_id, destination_id=destination_id)
                record = result.single()
            except Exception:
                record = None
                
            if not record or not record["path"]:
                cypher_fallback = """
                    MATCH (start {station_id: $origin_id})
                    MATCH (end {station_id: $destination_id})
                    MATCH p = shortestPath((start)-[:METRO_LINK|RAIL_LINK|INTERCHANGE_TO*..30]-(end))
                    RETURN p as path, reduce(t = 0, r in relationships(p) | t + coalesce(r.travel_time_min, 5)) as weight
                """
                result = session.run(cypher_fallback, origin_id=origin_id, destination_id=destination_id)
                record = result.single()
                if not record or not record["path"]:
                    return {
                        "found": False,
                        "origin_id": origin_id,
                        "destination_id": destination_id,
                        "total_time_min": 0,
                        "path": [],
                        "legs": []
                    }
            
            path = record["path"]
            total_time = record["weight"]
            
            stations = []
            for node in path.nodes:
                stations.append({
                    "station_id": node["station_id"],
                    "name": node["name"],
                    "lines": list(node["lines"]) if node["lines"] else []
                })
                
            legs = []
            nodes_list = list(path.nodes)
            rels_list = list(path.relationships)
            for i in range(len(rels_list)):
                rel = rels_list[i]
                start_node = nodes_list[i]
                end_node = nodes_list[i+1]
                
                legs.append({
                    "from_station_id": start_node["station_id"],
                    "to_station_id": end_node["station_id"],
                    "type": rel.type,
                    "line": rel.get("line", "walk"),
                    "travel_time_min": rel.get("travel_time_min", 5)
                })
                
            return {
                "found": True,
                "origin_id": origin_id,
                "destination_id": destination_id,
                "total_time_min": int(total_time),
                "path": stations,
                "legs": legs
            }


# ── CHEAPEST ROUTE (Dijkstra by fare) ────────────────────────────────────────

def query_cheapest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
    fare_class: str = "standard",
) -> dict:
    """
    Find the cheapest path between two stations, minimising total estimated fare.
    """
    with _driver() as driver:
        with driver.session() as session:
            cypher = """
                MATCH (start {station_id: $origin_id})
                MATCH (end {station_id: $destination_id})
                MATCH p = (start)-[:METRO_LINK|RAIL_LINK|INTERCHANGE_TO*..15]-(end)
                RETURN p as path, reduce(t = 0, r in relationships(p) | t + coalesce(r.travel_time_min, 5)) as weight
                LIMIT 5
            """
            result = session.run(cypher, origin_id=origin_id, destination_id=destination_id)
            records = list(result)
            if not records:
                return {"found": False, "total_fare_usd": 0.0, "stations": [], "legs": []}
            
            best_path = None
            best_fare = float('inf')
            best_legs = []
            best_stations = []
            
            for rec in records:
                path = rec["path"]
                nodes_list = list(path.nodes)
                rels_list = list(path.relationships)
                
                total_fare = 0.0
                stations = []
                
                for n in nodes_list:
                    stations.append({
                        "station_id": n["station_id"],
                        "name": n["name"],
                        "lines": list(n["lines"]) if n["lines"] else []
                    })
                    
                for r in rels_list:
                    rel_type = r.type
                    if rel_type == "METRO_LINK":
                        total_fare += 0.5
                    elif rel_type == "RAIL_LINK":
                        total_fare += 1.5 if fare_class == "standard" else 2.5
                    else:
                        total_fare += 0.0
                
                if total_fare < best_fare:
                    best_fare = total_fare
                    best_path = path
                    best_stations = stations
                    
                    best_legs = []
                    for i in range(len(rels_list)):
                        rel = rels_list[i]
                        best_legs.append({
                            "from_station_id": nodes_list[i]["station_id"],
                            "to_station_id": nodes_list[i+1]["station_id"],
                            "type": rel.type,
                            "line": rel.get("line", "walk"),
                            "travel_time_min": rel.get("travel_time_min", 5)
                        })
                        
            return {
                "found": True,
                "total_fare_usd": round(best_fare, 2),
                "stations": best_stations,
                "legs": best_legs
            }


# ── ALTERNATIVE ROUTES (avoiding a station) ───────────────────────────────────

def query_alternative_routes(
    origin_id: str,
    destination_id: str,
    avoid_station_id: str,
    network: str = "auto",
    max_routes: int = 3,
) -> list[list[dict]]:
    """
    Find paths between two stations that avoid a specific intermediate station.
    """
    with _driver() as driver:
        with driver.session() as session:
            cypher = """
                MATCH (start {station_id: $origin_id})
                MATCH (end {station_id: $destination_id})
                MATCH p = (start)-[:METRO_LINK|RAIL_LINK|INTERCHANGE_TO*..15]-(end)
                WHERE none(node in nodes(p) WHERE node.station_id = $avoid_station_id)
                RETURN p as path
                LIMIT $max_routes
            """
            result = session.run(cypher, origin_id=origin_id, destination_id=destination_id, avoid_station_id=avoid_station_id, max_routes=max_routes)
            
            routes = []
            for rec in result:
                path = rec["path"]
                nodes_list = list(path.nodes)
                rels_list = list(path.relationships)
                
                legs = []
                for i in range(len(rels_list)):
                    rel = rels_list[i]
                    legs.append({
                        "from_station_id": nodes_list[i]["station_id"],
                        "to_station_id": nodes_list[i+1]["station_id"],
                        "type": rel.type,
                        "line": rel.get("line", "walk"),
                        "travel_time_min": rel.get("travel_time_min", 5)
                    })
                routes.append(legs)
            return routes


# ── CROSS-NETWORK INTERCHANGE PATH ───────────────────────────────────────────

def query_interchange_path(origin_id: str, destination_id: str) -> dict:
    """
    Find a path between a metro station and a national rail station (or vice versa)
    crossing the network boundary via interchange relationships.
    """
    route = query_shortest_route(origin_id, destination_id)
    if not route["found"]:
        return {"found": False, "stations": [], "interchange_points": [], "total_time_min": 0}
        
    interchange_points = []
    legs = route["legs"]
    for leg in legs:
        if leg["type"] == "INTERCHANGE_TO":
            interchange_points.append(leg["from_station_id"])
            
    return {
        "found": True,
        "stations": route["path"],
        "interchange_points": list(set(interchange_points)),
        "total_time_min": route["total_time_min"]
    }


# ── DELAY RIPPLE ANALYSIS ─────────────────────────────────────────────────────

def query_delay_ripple(delayed_station_id: str, hops: int = 2) -> list[dict]:
    """
    Find all stations within N hops of a delayed or disrupted station.
    """
    with _driver() as driver:
        with driver.session() as session:
            cypher = """
                MATCH (s {station_id: $delayed_station_id})
                MATCH p = (s)-[:METRO_LINK|RAIL_LINK*1..$hops]-(affected)
                WITH affected, min(length(p)) as hops_away
                RETURN affected.station_id as station_id, affected.name as name, affected.lines as lines, hops_away
                ORDER BY hops_away
            """
            result = session.run(cypher, delayed_station_id=delayed_station_id, hops=hops)
            
            results = []
            for rec in result:
                results.append({
                    "station_id": rec["station_id"],
                    "name": rec["name"],
                    "hops_away": rec["hops_away"],
                    "lines_affected": list(rec["lines"]) if rec["lines"] else []
                })
            return results


# ── STATION CONNECTIONS ───────────────────────────────────────────────────────

def query_station_connections(station_id: str) -> list[dict]:
    """
    List all direct connections from a given station.
    """
    with _driver() as driver:
        with driver.session() as session:
            cypher = """
                MATCH (s {station_id: $station_id})-[r:METRO_LINK|RAIL_LINK|INTERCHANGE_TO]-(neighbor)
                RETURN neighbor.station_id as neighbor_id, 
                       neighbor.name as neighbor_name, 
                       type(r) as type, 
                       coalesce(r.line, 'walk') as line, 
                       coalesce(r.travel_time_min, 5) as travel_time
            """
            result = session.run(cypher, station_id=station_id)
            return [dict(row) for row in result]
