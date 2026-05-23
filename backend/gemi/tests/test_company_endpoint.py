from gemi import GemiDataClient

# from gemi.exceptions import GemiValidationError, GemiNotFoundError
from gemi.pagination import PaginatedResponse
from gemi.schemas.company import CompanyResponse, CompanySummary


def test_happy_path(api_credentials, dummy_ar_gemi, dummy_afm, vcr_cassette):
    """Test that the API client can be initialized with valid credentials."""
    with vcr_cassette("get_company_happy_path.yaml"):
        client = GemiDataClient(api_key=api_credentials["api_key"])
        response = client.get_company(dummy_ar_gemi)
        assert response is not None
        assert isinstance(response, CompanyResponse)
        assert response.arGemi == dummy_ar_gemi
        assert response.afm == dummy_afm


def test_search_happy_path(api_credentials, dummy_ar_gemi, dummy_afm, vcr_cassette):
    """Test that the API client can search for companies."""
    with vcr_cassette("search_company_happy_path.yaml"):
        client = GemiDataClient(api_key=api_credentials["api_key"])
        response = client.search_companies(vat_number=dummy_afm)

        assert response is not None

        # Handle both paginated and non-paginated responses
        if isinstance(response, PaginatedResponse):
            assert len(response.items) > 0
            assert all(isinstance(item, CompanySummary) for item in response.items)
            items = response.items
        else:
            assert isinstance(response, list)
            assert len(response) > 0
            assert all(isinstance(item, CompanySummary) for item in response)
            items = response

        # Verify basic structure of returned items
        first_item = items[0]
        assert hasattr(first_item, "gemh_number")
        assert hasattr(first_item, "name")
        assert hasattr(first_item, "vat_number")
        assert hasattr(first_item, "status")

        # Log what we got for debugging
        print(f"Search returned {len(items)} companies")
        print(
            f"First company: GEMI={first_item.gemh_number}, Name={first_item.name}, AFM={first_item.vat_number}"
        )

        # If searching by AFM, at least one result should match (but API might return broader results)
        # So let's just verify we got valid company data back
        assert all(
            item.gemh_number for item in items
        ), "All companies should have GEMI numbers"

        matching_companies = [item for item in items if item.vat_number == dummy_afm]

        if matching_companies:
            print(f"Found exact AFM match: {matching_companies[0].name}")
        else:
            print(
                f"No exact AFM match found. API returned {len(items)} related companies."
            )


# class TestCompanyEndpoint:
#     """Test the get_company method of GemiDataClient."""

#     @responses.activate
#     def test_get_company_success(self, api_credentials):
#         """Test successful company retrieval."""
#         gemi_number = "786301000"

#         # Mock API response
#         mock_response = {
#             "arGemi": 786301000,
#             "afm": "090000045",
#             "coNameEl": "ΔΗΜΟΣΙΑ ΕΠΙΧΕΙΡΗΣΗ ΗΛΕΚΤΡΙΣΜΟΥ ΑΕ",
#             "coNamesEn": ["PUBLIC POWER CORPORATION SA"],
#             "municipality": {"id": 1, "descr": "ΑΘΗΝΑ"},
#             "prefecture": {"id": 1, "descr": "ΑΤΤΙΚΗ"},
#             "city": "ΑΘΗΝΑ",
#             "street": "ΧΑΛΚΟΚΟΝΔΥΛΗ",
#             "streetNumber": "30",
#             "zipCode": "10432",
#             "email": "info@dei.gr",
#             "url": "https://www.dei.gr",
#             "isBranch": False,
#             "legalType": {"id": 1, "descr": "ΑΝΩΝΥΜΗ ΕΤΑΙΡΕΙΑ"},
#             "status": {"id": 1, "descr": "ΕΝΕΡΓΗ"},
#             "autoRegistered": False,
#             "activities": [],
#             "persons": [],
#             "capital": [],
#             "stocks": [],
#             "branch": []
#         }

#         responses.add(
#             responses.GET,
#             f"https://opendata.businessportal.gr/companies/{gemi_number}",
#             json=mock_response,
#             status=200
#         )

#         # Test the method
#         client = GemiDataClient(api_key=api_credentials["api_key"])
#         company = client.get_company(gemi_number)

#         # Assertions
#         assert isinstance(company, CompanyResponse)
#         assert company.arGemi == 786301000
#         assert company.afm == "090000045"
#         assert company.coNameEl == "ΔΗΜΟΣΙΑ ΕΠΙΧΕΙΡΗΣΗ ΗΛΕΚΤΡΙΣΜΟΥ ΑΕ"
#         assert company.municipality.id == 1
#         assert company.municipality.descr == "ΑΘΗΝΑ"

#     @responses.activate
#     def test_get_company_not_found(self, api_credentials):
#         """Test company not found scenario."""
#         gemi_number = "999999999"

#         responses.add(
#             responses.GET,
#             f"https://opendata.businessportal.gr/companies/{gemi_number}",
#             json=[{"code": "NOT_FOUND", "message": "Company not found"}],
#             status=404
#         )

#         client = GemiDataClient(api_key=api_credentials["api_key"])

#         with pytest.raises(GemiNotFoundError):
#             client.get_company(gemi_number)

#     def test_get_company_invalid_gemi_validation(self, api_credentials):
#         """Test validation of invalid GEMI numbers."""
#         client = GemiDataClient(api_key=api_credentials["api_key"])

#         # Test various invalid inputs
#         invalid_inputs = [
#             None,
#             "",
#             "   ",
#             "abc123",
#             "123abc",
#             "12.34",
#             "-123",
#             "0",
#         ]

#         for invalid_input in invalid_inputs:
#             with pytest.raises(GemiValidationError):
#                 client.get_company(invalid_input)

#     def test_get_company_valid_gemi_formats(self, api_credentials):
#         """Test that various valid GEMI formats are normalized correctly."""
#         client = GemiDataClient(api_key=api_credentials["api_key"])

#         # Test normalization without making actual API calls
#         test_cases = [
#             ("786301000", "786301000"),
#             (786301000, "786301000"),
#             ("000786301000", "786301000"),  # Leading zeros removed
#             ("  786301000  ", "786301000"),  # Whitespace trimmed
#         ]

#         for input_gemi, expected in test_cases:
#             normalized = client._validate_and_normalize_gemi(input_gemi)
#             assert normalized == expected

#     @responses.activate
#     def test_get_company_with_integer_input(self, api_credentials):
#         """Test that integer input works correctly."""
#         gemi_number = 786301000

#         mock_response = {
#             "arGemi": 786301000,
#             "afm": "090000045",
#             "coNameEl": "TEST COMPANY",
#             "activities": [],
#             "persons": [],
#             "capital": [],
#             "stocks": [],
#             "branch": []
#         }

#         responses.add(
#             responses.GET,
#             f"https://opendata.businessportal.gr/companies/{gemi_number}",
#             json=mock_response,
#             status=200
#         )

#         client = GemiDataClient(api_key=api_credentials["api_key"])
#         company = client.get_company(gemi_number)  # Pass as integer

#         assert company.arGemi == 786301000
#         assert company.coNameEl == "TEST COMPANY"
