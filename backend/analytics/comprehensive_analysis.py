from .entity_analysis import EntityAnalyzer
from .financial_analysis import FinancialAnalyzer
from .network_analysis import (
    create_entity_network,
    create_organization_decision_network,
)
from .text_analysis import DecisionTextAnalyzer


def run_comprehensive_analysis():
    """Run all analyses and generate insights."""
    print("Starting comprehensive analysis...")

    # 1. Text Analysis
    print("1. Analyzing decision text patterns...")
    text_analyzer = DecisionTextAnalyzer()
    text_analyzer.prepare_data()
    embeddings = text_analyzer.create_semantic_embeddings()
    clusters = text_analyzer.cluster_decisions(embeddings, n_clusters=8)
    reduced_2d = text_analyzer.reduce_dimensions(embeddings)
    text_analyzer.visualize_clusters(reduced_2d, clusters)

    # 2. Network Analysis
    print("2. Creating network visualizations...")
    org_network = create_organization_decision_network()
    entity_network = create_entity_network()

    # 3. Financial Analysis
    print("3. Analyzing financial patterns...")
    financial_analyzer = FinancialAnalyzer()
    monthly_spending = financial_analyzer.analyze_spending_patterns()
    kae_distribution = financial_analyzer.analyze_kae_distribution()

    # 4. Entity Analysis
    print("4. Analyzing entity relationships...")
    entity_analyzer = EntityAnalyzer()
    centrality_scores = entity_analyzer.analyze_entity_centrality()
    suspicious_patterns = entity_analyzer.find_suspicious_patterns()

    print("Analysis complete!")

    return {
        "text_clusters": clusters,
        "embeddings": embeddings,
        "networks": {"organizations": org_network, "entities": entity_network},
        "financial": {"monthly": monthly_spending, "kae": kae_distribution},
        "entities": {
            "centrality": centrality_scores,
            "suspicious": suspicious_patterns,
        },
    }
