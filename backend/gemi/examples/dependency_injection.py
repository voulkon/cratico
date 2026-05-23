"""Example of proper dependency injection pattern for the GEMI client."""

from gemi.src.client import GemiDataClient


class CompanyService:
    """Business logic service that depends on GEMI API."""

    def __init__(self, gemi_client: GemiDataClient):
        self.gemi_client = gemi_client

    def find_company_by_name(self, name: str):
        """Find company using injected client."""
        return self.gemi_client.companies.search_companies(name=name)


class ReportService:
    """Another service that uses GEMI API."""

    def __init__(self, gemi_client: GemiDataClient):
        self.gemi_client = gemi_client

    def generate_company_report(self, gemh_number: str):
        """Generate report using injected client."""
        company = self.gemi_client.companies.get_company(gemh_number)
        prefectures = self.gemi_client.reference.get_prefectures()
        # ... report logic
        return {"company": company, "prefectures": prefectures}


# Application setup - create ONE client instance and inject it
def create_app():
    """Application factory that sets up dependencies."""
    # Single client instance
    gemi_client = GemiDataClient(api_key="your-key")

    # Inject the same client into all services
    company_service = CompanyService(gemi_client)
    report_service = ReportService(gemi_client)

    return {
        "company_service": company_service,
        "report_service": report_service,
        "gemi_client": gemi_client,  # Available if needed directly
    }


# Usage
app = create_app()
companies = app["company_service"].find_company_by_name("ALPHA")
report = app["report_service"].generate_company_report("123456789")
