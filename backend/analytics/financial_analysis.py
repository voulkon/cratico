import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from core.models.decisions import Decision, DecisionAmountKAE
from django.db.models import Count, Sum


class FinancialAnalyzer:
    def analyze_spending_patterns(self):
        """Analyze spending patterns across organizations and time."""
        # Monthly spending by organization
        decisions = Decision.objects.filter(amount__isnull=False).select_related(
            "organization"
        )

        df = pd.DataFrame(
            decisions.values(
                "organization__label",
                "amount",
                "issue_date",
                "financial_year",
                "decision_type__label",
            )
        )

        df["issue_date"] = pd.to_datetime(df["issue_date"])
        df["month"] = df["issue_date"].dt.to_period("M")

        # Monthly aggregation
        monthly_spending = (
            df.groupby(["month", "organization__label"])["amount"]
            .sum()
            .unstack(fill_value=0)
        )

        return monthly_spending

    def analyze_kae_distribution(self):
        """Analyze KAE code distribution and amounts."""
        kae_data = (
            DecisionAmountKAE.objects.values(
                "kae", "decision__organization__label", "decision__financial_year"
            )
            .annotate(
                total_amount=Sum("amount"),
                decision_count=Count("decision", distinct=True),
            )
            .order_by("-total_amount")
        )

        return pd.DataFrame(kae_data)

    def find_financial_outliers(self, threshold=3):
        """Find decisions with unusual amounts (using z-score)."""
        from scipy import stats

        amounts = Decision.objects.filter(amount__isnull=False).values_list(
            "amount", flat=True
        )

        amounts_array = np.array([float(a) for a in amounts])
        z_scores = np.abs(stats.zscore(amounts_array))

        outlier_indices = np.where(z_scores > threshold)[0]

        # Get the actual decisions
        outlier_decisions = Decision.objects.filter(amount__isnull=False)[
            outlier_indices
        ]

        return outlier_decisions


def create_financial_dashboard():
    """Create comprehensive financial analysis dashboard."""
    analyzer = FinancialAnalyzer()

    # 1. Monthly spending heatmap
    monthly_data = analyzer.analyze_spending_patterns()

    plt.figure(figsize=(15, 10))
    sns.heatmap(monthly_data.T, cmap="YlOrRd", annot=False)
    plt.title("Monthly Spending by Organization")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()

    # 2. KAE distribution
    kae_data = analyzer.analyze_kae_distribution()

    plt.figure(figsize=(12, 8))
    top_kaes = kae_data.head(20)
    plt.barh(top_kaes["kae"], top_kaes["total_amount"])
    plt.title("Top 20 KAE Codes by Total Amount")
    plt.xlabel("Total Amount")
    plt.tight_layout()
    plt.show()

    return analyzer
