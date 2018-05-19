import sqlite3
import cbor
import json

conn = sqlite3.connect("state/descriptions.sqlite3")
cursor = conn.execute("SELECT full_id,cbor FROM descriptions")
descriptions = {d[0]: cbor.loads(d[1]) for d in cursor.fetchall()}
print(json.dumps(descriptions, indent=2))
