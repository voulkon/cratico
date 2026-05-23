import matplotlib.pyplot as plt
import networkx as nx
from core.models.decisions import Decision
from core.models.entities import DecisionEntityRelationship


def create_organization_decision_network():
    """Create a bipartite network of organizations and decisions."""
    G = nx.Graph()

    # Add nodes for organizations and decisions
    decisions = Decision.objects.select_related("organization").all()

    for decision in decisions:
        if decision.organization:
            org_id = f"org_{decision.organization.uid}"
            decision_id = f"dec_{decision.ada}"

            # Add nodes with attributes
            G.add_node(org_id, type="organization", label=decision.organization.label)
            G.add_node(decision_id, type="decision", amount=float(decision.amount or 0))

            # Add edge
            G.add_edge(org_id, decision_id)

    return G


def create_entity_network():
    """Create network of AFM entities and their relationships through decisions."""
    G = nx.Graph()

    # Get all relationships
    relationships = DecisionEntityRelationship.objects.select_related(
        "entity", "decision"
    ).all()

    # Group by decision to find entities that appear together
    from collections import defaultdict

    decision_entities = defaultdict(list)

    for rel in relationships:
        decision_entities[rel.decision.ada].append(rel.entity.afm)

    # Create edges between entities that appear in same decisions
    for decision_ada, entities in decision_entities.items():
        for i, entity1 in enumerate(entities):
            for entity2 in entities[i + 1 :]:
                if G.has_edge(entity1, entity2):
                    G[entity1][entity2]["weight"] += 1
                else:
                    G.add_edge(entity1, entity2, weight=1)

    return G


def visualize_network(G, title="Network Analysis"):
    """Visualize network with different layouts."""
    plt.figure(figsize=(15, 10))

    # Use spring layout for better visualization
    pos = nx.spring_layout(G, k=1, iterations=50)

    # Draw network
    nx.draw(
        G,
        pos,
        node_color="lightblue",
        node_size=300,
        with_labels=True,
        font_size=8,
        edge_color="gray",
        alpha=0.7,
    )

    plt.title(title)
    plt.show()
