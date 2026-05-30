"""
TransitFlow — Neo4j Seeder
Run once after starting Docker:
    python skeleton/seed_neo4j.py

Loads station and network data from train-mock-data/:
  - metro_stations.json         — city metro stations and adjacencies
  - national_rail_stations.json — national rail stations and adjacencies

Design your graph schema (node labels, relationship types, properties)
based on the data in these files, then implement the seed() function below.
"""

import json
import os
import sys

sys.path.insert(0, ".")

from neo4j import GraphDatabase
from skeleton.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

_DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "train-mock-data")
)


def _load(filename):
    with open(os.path.join(_DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


def seed():
    metro_stations = _load("metro_stations.json")
    rail_stations  = _load("national_rail_stations.json")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:

        session.run("MATCH (n) DETACH DELETE n")
        print("  Cleared existing graph data")

        print(f"  Metro stations: creating {len(metro_stations)} nodes...")
        for s in metro_stations:
            session.run(
                """
                CREATE (s:MetroStation {
                    station_id: $station_id,
                    name: $name,
                    lines: $lines
                })
                """,
                station_id=s["station_id"],
                name=s["name"],
                lines=s["lines"]
            )

        print(f"  National rail stations: creating {len(rail_stations)} nodes...")
        for s in rail_stations:
            session.run(
                """
                CREATE (s:NationalRailStation {
                    station_id: $station_id,
                    name: $name,
                    lines: $lines
                })
                """,
                station_id=s["station_id"],
                name=s["name"],
                lines=s["lines"]
            )

        print("  Metro links: creating adjacent connections...")
        for s in metro_stations:
            for adj in s["adjacent_stations"]:
                session.run(
                    """
                    MATCH (a:MetroStation {station_id: $station_id})
                    MATCH (b:MetroStation {station_id: $adj_id})
                    MERGE (a)-[r:METRO_LINK {line: $line}]->(b)
                    SET r.travel_time_min = $travel_time_min,
                        r.price_standard = 2.0, r.price_first = 2.0
                    """,
                    station_id=s["station_id"],
                    adj_id=adj["station_id"],
                    line=adj["line"],
                    travel_time_min=adj["travel_time_min"]
                )

        print("  National rail links: creating adjacent connections...")
        for s in rail_stations:
            for adj in s["adjacent_stations"]:
                session.run(
                    """
                    MATCH (a:NationalRailStation {station_id: $station_id})
                    MATCH (b:NationalRailStation {station_id: $adj_id})
                    MERGE (a)-[r:RAIL_LINK {line: $line}]->(b)
                    SET r.travel_time_min = $travel_time_min,
                        r.price_standard = 5.0, r.price_first = 8.5
                    """,
                    station_id=s["station_id"],
                    adj_id=adj["station_id"],
                    line=adj["line"],
                    travel_time_min=adj["travel_time_min"]
                )

        print("  Interchanges: creating cross-network connections...")
        for s in metro_stations:
            if s["is_interchange_national_rail"] and s["interchange_national_rail_station_id"]:
                session.run(
                    """
                    MATCH (m:MetroStation {station_id: $metro_id})
                    MATCH (r:NationalRailStation {station_id: $rail_id})
                    MERGE (m)-[i1:INTERCHANGE_TO]->(r)
                    MERGE (r)-[i2:INTERCHANGE_TO]->(m)
                    SET i1.walk_time_min = 5, i2.walk_time_min = 5
                    """,
                    metro_id=s["station_id"],
                    rail_id=s["interchange_national_rail_station_id"]
                )

    driver.close()
    print("\nNeo4j graph seeded successfully.")
    print("   Open http://localhost:7475 to explore the graph.")


if __name__ == "__main__":
    print("Connecting to Neo4j...")
    seed()