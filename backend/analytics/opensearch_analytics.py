from opensearchpy import OpenSearch


class OpenSearchAnalyzer:
    def __init__(self, host="localhost", port=9200):
        self.client = OpenSearch([{"host": host, "port": port}])

    def create_decision_aggregations(self):
        """Create complex aggregations for decision analysis."""
        query = {
            "size": 0,
            "aggs": {
                "by_organization": {
                    "terms": {"field": "organization.keyword", "size": 10},
                    "aggs": {
                        "total_amount": {"sum": {"field": "amount"}},
                        "by_month": {
                            "date_histogram": {
                                "field": "issue_date",
                                "calendar_interval": "month",
                            },
                            "aggs": {"monthly_amount": {"sum": {"field": "amount"}}},
                        },
                    },
                }
            },
        }

        response = self.client.search(index="decisions", body=query)

        return response["aggregations"]

    def semantic_search_similar_decisions(self, decision_text, size=10):
        """Find semantically similar decisions."""
        # This requires setting up vector search in OpenSearch
        query = {
            "query": {
                "more_like_this": {
                    "fields": ["subject"],
                    "like": decision_text,
                    "min_term_freq": 1,
                    "max_query_terms": 12,
                }
            },
            "size": size,
        }

        response = self.client.search(index="decisions", body=query)

        return response["hits"]["hits"]
