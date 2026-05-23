"""Constants for the POTHEN scraper package."""

# Base URLs
PARLIAMENT_BASE_URL = "https://www.hellenicparliament.gr"
DECLARATIONS_BASE_PATH = "/Organosi-kai-Leitourgia/epitropi-elegxou-ton-oikonomikon-ton-komaton-kai-ton-vouleftwn"

# Landing page for asset declarations
DECLARATIONS_LANDING_URL = f"{PARLIAMENT_BASE_URL}{DECLARATIONS_BASE_PATH}/dilosi-periousiakis-katastasis-arxiki"

# Year-specific declaration pages template
DECLARATIONS_YEAR_URL_TEMPLATE = f"{PARLIAMENT_BASE_URL}{DECLARATIONS_BASE_PATH}/Diloseis-Periousiakis-Katastasis{{year}}"

# HTTP settings
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_RATE_LIMIT_REQUESTS_PER_MINUTE = 10

# File settings
PDF_CHUNK_SIZE = 8192  # 8KB chunks for downloads
MAX_PDF_SIZE_MB = 50  # Maximum PDF file size to download

# Parsing settings
MIN_PDF_CONTENT_LENGTH = 100  # Minimum characters in extracted text to be valid
