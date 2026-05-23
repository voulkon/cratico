import networkx as nx
import pandas as pd
from core.models.entities import DecisionEntityRelationship
from django.db.models import Count, Sum


class EntityAnalyzer:
    def analyze_entity_centrality(self):
        """Find most central/important entities in the network."""
        # Create entity co-occurrence network
        G = self.create_entity_cooccurrence_network()

        # Calculate centrality measures
        centrality_measures = {
            "degree": nx.degree_centrality(G),
            "betweenness": nx.betweenness_centrality(G),
            "closeness": nx.closeness_centrality(G),
            "pagerank": nx.pagerank(G),
        }

        # Convert to DataFrame
        centrality_df = pd.DataFrame(centrality_measures)
        centrality_df["afm"] = centrality_df.index

        return centrality_df.sort_values("pagerank", ascending=False)

    def find_suspicious_patterns(self):
        """Identify potentially suspicious patterns in entity relationships."""
        # Find entities that appear as multiple roles
        multi_role_entities = (
            DecisionEntityRelationship.objects.values("entity__afm")
            .annotate(
                role_count=Count("role", distinct=True),
                decision_count=Count("decision", distinct=True),
                total_amount=Sum("decision__amount"),
            )
            .filter(role_count__gt=1)
            .order_by("-decision_count")
        )

        return pd.DataFrame(multi_role_entities)

    def create_entity_cooccurrence_network(self):
        """Create network based on entities appearing in same decisions."""
        # This is the same as in network_analysis.py but included for completeness
        G = nx.Graph()

        relationships = DecisionEntityRelationship.objects.select_related(
            "entity", "decision"
        ).all()

        from collections import defaultdict

        decision_entities = defaultdict(list)

        for rel in relationships:
            decision_entities[rel.decision.ada].append(rel.entity.afm)

        for decision_ada, entities in decision_entities.items():
            for i, entity1 in enumerate(entities):
                for entity2 in entities[i + 1 :]:
                    if G.has_edge(entity1, entity2):
                        G[entity1][entity2]["weight"] += 1
                    else:
                        G.add_edge(entity1, entity2, weight=1)

        return G
