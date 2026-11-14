"""Write the grafeo 0.5.44 databases the migration tests open with grafeo 0.6.

Run from an empty scratch directory, outside this repository's environment:

    uv run --no-project --with grafeo==0.5.44 python make_fixtures.py <output-dir>

and copy ``graph.grafeo`` and ``graph-waldir/`` from the output directory here.
``graph.grafeo`` is a single-file database with a vector, a text and a property
index; ``graph-waldir`` is a WAL-directory database (0.5.x wrote one for a path
without the ``.grafeo`` extension) with the same data.
"""

from __future__ import annotations

import os
import sys

import grafeo


def fill(db: grafeo.GrafeoDB) -> None:
    alix = db.create_node(["Person"], {"name": "Alix", "age": 30, "score": 1.5, "emb": [1.0, 0.0, 0.0]})
    gus = db.create_node(["Person"], {"name": "Gus", "age": 25, "score": 2.25, "emb": [0.0, 1.0, 0.0]})
    acme = db.create_node(["Company"], {"name": "Acme", "bio": "graph database company"})
    db.create_edge(alix.id, gus.id, "KNOWS", {"since": 2020, "w": 0.5})
    db.create_edge(gus.id, acme.id, "WORKS_AT", {"since": 2021})
    db.create_vector_index("Person", "emb", 3, "cosine")
    db.create_text_index("Company", "bio")
    db.create_property_index("name")


def main(out: str) -> None:
    assert grafeo.__version__.startswith("0.5.44"), grafeo.__version__
    for name in ("graph.grafeo", "graph-waldir"):
        db = grafeo.GrafeoDB(os.path.join(out, name))
        fill(db)
        db.close()


if __name__ == "__main__":
    main(sys.argv[1])
