# GEMI OpenData API Python Client

A comprehensive Python client library for the Greek GEMI OpenData API.

## Installation

```bash
pip install gemi-opendata-client
```

## Quick Start

```python
import os
from gemi import GemiDataClient

# Initialize the client
client = GemiDataClient(api_key="your-api-key")

# Or use environment variables
os.environ["GEMI_API_KEY"] = "your-api-key"
client = GemiDataClient()  # Will automatically load from environment

# Search for companies
companies = client.companies.search_companies(name="ALPHA")
for company in companies:
    print(f"{company.name} - {company.gemh_number}")

# Get detailed company information
company_detail = client.companies.get_company("123456789")
print(f"Company: {company_detail.name}")
print(f"Status: {company_detail.status}")
print(f"VAT: {company_detail.vat_number}")

# Get reference data
prefectures = client.reference.get_prefectures()
for prefecture in prefectures:
    print(f"{prefecture.id}: {prefecture.name}")
```

## Advanced Usage

### Pagination

```python
# Get paginated results
paginated_companies = client.companies.search_companies(
    name="ALPHA",
    page=1,
    page_size=50
)
print(f"Total companies: {paginated_companies.total_count}")
print(f"Current page: {paginated_companies.page}")

# Iterate through all results automatically
for company in client.companies.search_companies_iter(name="ALPHA"):
    print(company.name)
```

### Configuration

```python
from gemi import GemiDataClient, GemiConfig

# Create custom configuration
config = GemiConfig(
    api_key="your-api-key",
    timeout=60,
    max_retries=5
)

client = GemiDataClient.from_config(config)
```

### Caching

```python
from gemi import GemiDataClient
from gemi.cache import MemoryCache

# Use custom cache settings
cache = MemoryCache(default_ttl=600)  # 10 minutes
client = GemiDataClient(api_key="your-key")

# Reference data is automatically cached
prefectures = client.reference.get_prefectures()  # Fetched from API
prefectures = client.reference.get_prefectures()  # Returned from cache
```

### Error Handling

```python
from gemi import GemiDataClient
from gemi.exceptions import GemiAPIError, GemiNotFoundError, GemiRateLimitError

client = GemiDataClient(api_key="your-key")

try:
    company = client.companies.get_company("123456789")
except GemiNotFoundError:
    print("Company not found")
except GemiRateLimitError as e:
    print(f"Rate limited. Retry after {e.retry_after} seconds")
except GemiAPIError as e:
    print(f"API error: {e}")
```

## Environment Variables

The client supports the following environment variables:

- `GEMI_API_KEY`: Your API key
- `GEMI_BASE_URL`: Custom base URL (optional)
- `GEMI_TIMEOUT`: Request timeout in seconds (default: 30)
- `GEMI_MAX_RETRIES`: Maximum number of retries (default: 3)

## API Reference

### Client

#### `GemiDataClient(api_key, base_url=None, config=None)`

Main client class that provides access to all API services.

### Services

#### `client.companies`

- `search_companies(**filters)` - Search for companies
- `search_companies_iter(**filters)` - Iterator for paginated results
- `get_company(gemh_number)` - Get detailed company information

#### `client.reference`

- `get_local_offices()` - Get GEMI local offices
- `get_prefectures()` - Get prefectures
- `get_municipalities()` - Get municipalities
- `get_business_statuses()` - Get business statuses
- `get_legal_forms()` - Get legal forms
- `get_organ_types()` - Get organ types
- `get_document_types()` - Get document types

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Run the test suite: `pytest`
6. Submit a pull request

## License

MIT License
