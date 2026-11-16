"""Load the Silicon Valley (Pied Piper) demo dataset from grafeo.ai into a database file for grafeo-mcp.

Run:  uv run --with "grafeo-datasets[grafeo]" examples/load_pied_piper.py [pied-piper.grafeo]

Then point the server at the file (GRAFEO_DB_PATH, as in the configs next to this script) and ask:
"How is Son of Anton related to Anton?" or "Does Jian-Yang's fridge talk?".
"""

import sys

import grafeo
from grafeo_datasets import silicon_valley

path = sys.argv[1] if len(sys.argv) > 1 else "pied-piper.grafeo"
db = grafeo.GrafeoDB(path)
silicon_valley.load(db, vectors=True)  # MiniLM embeddings (384 dimensions) and a vector index per label
print(f"{path}: {db.node_count} nodes, {db.edge_count} edges")
db.close()
