import sqlite3
import json

# Connect to graph database
conn = sqlite3.connect('opencrab_data/graph.db')
cursor = conn.cursor()

# List all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in cursor.fetchall()]
print("=== Database Tables ===")
for table in tables:
    print(f"  - {table}")

print("\n=== Graph Nodes ===")
cursor.execute("SELECT * FROM graph_nodes LIMIT 20")
columns = [description[0] for description in cursor.description]
nodes = cursor.fetchall()
print(f"Found {len(nodes)} nodes")
for i, node in enumerate(nodes[:10], 1):
    node_dict = dict(zip(columns, node))
    print(f"\n{i}. {node_dict.get('id', 'unknown')}")
    print(f"   Type: {node_dict.get('node_type', 'N/A')}")
    print(f"   Space: {node_dict.get('space', 'N/A')}")
    if 'properties' in node_dict and node_dict['properties']:
        try:
            props = json.loads(node_dict['properties']) if isinstance(node_dict['properties'], str) else node_dict['properties']
            print(f"   Name: {props.get('name', 'N/A')}")
            if 'description' in props:
                desc = props['description'][:100] + '...' if len(props['description']) > 100 else props['description']
                print(f"   Desc: {desc}")
        except:
            pass

print("\n=== Graph Edges ===")
cursor.execute("SELECT * FROM graph_edges LIMIT 20")
columns = [description[0] for description in cursor.description]
edges = cursor.fetchall()
print(f"Found {len(edges)} edges")
for i, edge in enumerate(edges[:10], 1):
    edge_dict = dict(zip(columns, edge))
    print(f"\n{i}. {edge_dict.get('source_id', '?')} --[{edge_dict.get('relation', '?')}]--> {edge_dict.get('target_id', '?')}")

conn.close()
