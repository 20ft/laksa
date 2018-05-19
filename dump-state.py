import sqlite3
import cbor
import json

conn = sqlite3.connect("state/state.sqlite3")
cursor = conn.execute("SELECT rid,cbor FROM sessions")
sessions = {d[0]: cbor.loads(d[1]) for d in cursor.fetchall()}
print(sessions)
