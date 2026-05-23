"""Example showing why custom exceptions are beneficial."""

import requests


# BAD: Using raw requests exceptions
def bad_api_call():
    try:
        response = requests.get(
            "https://api.example.com/companies/123",
            timeout=10,
        )
        response.raise_for_status()  # This loses context!
        return response.json()
    except requests.exceptions.HTTPError as e:
        # What information do we have?
        print(f"Error: {e}")  # "404 Client Error: Not Found for url: ..."
        # We don't know:
        # - Was it a missing company or invalid endpoint?
        # - What was the actual error message from the API?
        # - Can we retry this error or not?
        raise


# GOOD: Using custom exceptions with context
class CompanyNotFoundError(Exception):
    def __init__(self, company_id: str, api_message: str = None):
        self.company_id = company_id
        self.api_message = api_message
        super().__init__(
            f"Company {company_id} not found: {api_message or 'Unknown error'}"
        )


def good_api_call(company_id: str):
    try:
        response = requests.get(
            f"https://api.example.com/companies/{company_id}",
            timeout=10,
        )
        if response.status_code == 404:
            # Extract the actual API error message
            try:
                error_data = response.json()
                api_message = error_data.get("message", "Company not found")
            except:
                api_message = "Company not found"
            raise CompanyNotFoundError(company_id, api_message)
        response.raise_for_status()
        return response.json()
    except CompanyNotFoundError:
        raise  # Re-raise our custom exception
    except requests.exceptions.HTTPError as e:
        # Handle other HTTP errors
        raise APIError(f"Unexpected API error: {e}")


# Usage benefits:
try:
    company = good_api_call("123")
except CompanyNotFoundError as e:
    print(f"Specific handling: {e.company_id} not found")
    # Maybe try alternative lookup or create new company
except APIError as e:
    print(f"General API error: {e}")
    # Maybe retry or log for investigation
