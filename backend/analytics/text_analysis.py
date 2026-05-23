import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from core.models.decisions import Decision
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN, KMeans
from sklearn.decomposition import PCA, TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.manifold import TSNE


class DecisionTextAnalyzer:
    def __init__(self):
        self.vectorizer = None
        self.embeddings = None
        self.decisions_df = None

    def prepare_data(self):
        """Load and prepare decision data."""
        decisions = Decision.objects.select_related("organization").values(
            "ada",
            "subject",
            "amount",
            "financial_year",
            "organization__label",
            "decision_type__label",
        )

        self.decisions_df = pd.DataFrame(decisions)
        return self.decisions_df

    def create_tfidf_embeddings(self, max_features=1000):
        """Create TF-IDF embeddings from decision subjects."""
        subjects = self.decisions_df["subject"].fillna("")

        self.vectorizer = TfidfVectorizer(
            max_features=max_features,
            stop_words="english",  # Add Greek stopwords if available
            ngram_range=(1, 2),
        )

        tfidf_matrix = self.vectorizer.fit_transform(subjects)
        return tfidf_matrix.toarray()

    def create_semantic_embeddings(self):
        """Create semantic embeddings using SentenceTransformers."""
        model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        subjects = self.decisions_df["subject"].fillna("").tolist()

        embeddings = model.encode(subjects)
        return embeddings

    def reduce_dimensions(self, embeddings, method="tsne", n_components=2):
        """Reduce dimensionality for visualization."""
        if method == "pca":
            reducer = PCA(n_components=n_components)
        elif method == "tsne":
            reducer = TSNE(n_components=n_components, random_state=42)
        elif method == "svd":
            reducer = TruncatedSVD(n_components=n_components)

        reduced = reducer.fit_transform(embeddings)
        return reduced

    def cluster_decisions(self, embeddings, method="kmeans", n_clusters=5):
        """Cluster decisions based on embeddings."""
        if method == "kmeans":
            clusterer = KMeans(n_clusters=n_clusters, random_state=42)
        elif method == "dbscan":
            clusterer = DBSCAN(eps=0.5, min_samples=5)

        clusters = clusterer.fit_predict(embeddings)
        return clusters

    def visualize_clusters(
        self, reduced_embeddings, clusters, title="Decision Clusters"
    ):
        """Visualize clusters in 2D space."""
        plt.figure(figsize=(12, 8))

        unique_clusters = np.unique(clusters)
        colors = plt.cm.Set3(np.linspace(0, 1, len(unique_clusters)))

        for cluster, color in zip(unique_clusters, colors):
            mask = clusters == cluster
            plt.scatter(
                reduced_embeddings[mask, 0],
                reduced_embeddings[mask, 1],
                c=[color],
                label=f"Cluster {cluster}",
                alpha=0.7,
            )

        plt.title(title)
        plt.xlabel("Dimension 1")
        plt.ylabel("Dimension 2")
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.show()


# Usage example
def analyze_decision_patterns():
    analyzer = DecisionTextAnalyzer()
    analyzer.prepare_data()

    # Create embeddings
    semantic_embeddings = analyzer.create_semantic_embeddings()

    # Reduce dimensions
    reduced_2d = analyzer.reduce_dimensions(semantic_embeddings, method="tsne")

    # Cluster
    clusters = analyzer.cluster_decisions(semantic_embeddings, n_clusters=8)

    # Visualize
    analyzer.visualize_clusters(reduced_2d, clusters)

    return analyzer, clusters
