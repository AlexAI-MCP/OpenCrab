import sqlite3
import json
from collections import defaultdict

# Connect to graph database
conn = sqlite3.connect('opencrab_data/graph.db')
cursor = conn.cursor()

print("=" * 80)
print("  OPENCRAB ONTOLOGY GRAPH - Customer Churn Analysis")
print("=" * 80)

# Get nodes by space
cursor.execute("SELECT node_id, node_type, space_id, properties FROM graph_nodes")
nodes_data = cursor.fetchall()

nodes_by_space = defaultdict(list)
node_names = {}

for node_id, node_type, space, props_json in nodes_data:
    try:
        props = json.loads(props_json) if props_json else {}
        name = props.get('name', props.get('title', node_type))
        node_names[node_id] = f"{name} ({node_type})"
        nodes_by_space[space or 'unknown'].append({
            'id': node_id,
            'type': node_type,
            'name': name,
            'props': props
        })
    except:
        node_names[node_id] = f"{node_type}"
        nodes_by_space[space or 'unknown'].append({
            'id': node_id,
            'type': node_type,
            'name': node_type,
            'props': {}
        })

print("\n📊 NODES BY SPACE:")
print("-" * 80)
for space, nodes in sorted(nodes_by_space.items()):
    print(f"\n🔸 {space.upper()} ({len(nodes)} nodes)")
    for node in nodes[:5]:  # Show first 5 per space
        print(f"   • {node['name']} [{node['type']}]")
        if 'description' in node['props']:
            desc = node['props']['description'][:60] + '...' if len(node['props']['description']) > 60 else node['props']['description']
            print(f"     └─ {desc}")

# Get edges with meaningful labels
cursor.execute("SELECT from_id, to_id, relation, properties FROM graph_edges")
edges_data = cursor.fetchall()

print("\n\n🔗 KEY RELATIONSHIPS:")
print("-" * 80)

# Group edges by relation type
edges_by_relation = defaultdict(list)
for source_id, target_id, relation, props_json in edges_data:
    source_name = node_names.get(source_id, source_id)
    target_name = node_names.get(target_id, target_id)
    edges_by_relation[relation].append((source_name, target_name))

for relation, edge_list in sorted(edges_by_relation.items())[:10]:  # Show first 10 relation types
    print(f"\n📌 Relation: {relation.upper()}")
    for i, (source, target) in enumerate(edge_list[:3], 1):  # Show first 3 edges per relation
        print(f"   {i}. {source}")
        print(f"      └─> {target}")

# Create a visual graph representation for customer-related concepts
print("\n\n🎯 CUSTOMER CHURN ONTOLOGY GRAPH:")
print("-" * 80)
print("""
┌─────────────────────────────────────────────────────────────────────┐
│                     CUSTOMER CHURN ONTOLOGY                         │
└─────────────────────────────────────────────────────────────────────┘

[SUBJECT Space - Who]
  └─> Users, Teams, Organizations
      └─> Alice Chen (User)
      └─> Bob Kim (User)  
      └─> Data Team (Team)
      └─> ACME Corp (Org)
      └─> RAG Agent (Agent)

[RESOURCE Space - What]
  └─> Projects, Datasets, Tools, APIs
      └─> Analytics Platform (Project)
      └─> User Events Dataset (Dataset)
      └─> dbt (Tool)
      └─> Query API (API)

[EVIDENCE Space - Raw Data]
  └─> Text Units, Log Entries
      └─> Customer Churn Analysis Document
      └─> Q4 2025 Incident Report
      └─> Cache Analysis Report

[CONCEPT Space - Ideas]
  └─> Entities, Topics, Classes
      └─> Customer Behavior (Entity)
      └─> Churn Rate (Concept)
      └─> Retention Strategy (Topic)

[OUTCOME Space - Results]
  └─> KPIs, Risks
      └─> Revenue Impact (KPI)
      └─> Customer Satisfaction (Outcome)

[LEVER Space - Controls]
  └─> Control Variables
      └─> Cache TTL (Lever)
      └─> Support Response Time (Lever)

[POLICY Space - Rules]
  └─> Access, Sensitivity, Approval
      └─> Data Access Policy v1.3 (Policy)

""")

# Connection examples
print("\n🔀 SAMPLE CONNECTIONS:")
print("-" * 80)
cursor.execute("""
    SELECT from_id, to_id, relation 
    FROM graph_edges 
    LIMIT 10
""")

for i, (src, tgt, rel) in enumerate(cursor.fetchall(), 1):
    src_name = node_names.get(src, src)[:40]
    tgt_name = node_names.get(tgt, tgt)[:40]
    print(f"{i}. {src_name}")
    print(f"   --[{rel}]--> {tgt_name}\n")

print("\n" + "=" * 80)
print("  Total Nodes: %d | Total Edges: %d" % (len(nodes_data), len(edges_data)))
print("=" * 80)

conn.close()
