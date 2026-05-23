from django.contrib.postgres.search import SearchVectorField
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


class Company(models.Model):
    """Main company model based on GEMI API response."""

    # Primary identifiers
    ar_gemi = models.BigIntegerField(
        unique=True, db_index=True, help_text="GEMI registration number"
    )
    afm = models.CharField(
        max_length=9,
        validators=[RegexValidator(r"^\d{9}$", "AFM must be exactly 9 digits")],
        null=True,
        blank=True,
        db_index=True,
        help_text="Tax identification number (AFM)",
    )

    # Company names and titles
    co_name_el = models.TextField(
        null=True, blank=True, help_text="Company name in Greek"
    )
    co_names_en = models.JSONField(default=list, help_text="Company names in English")
    co_titles_el = models.JSONField(default=list, help_text="Company titles in Greek")
    co_titles_en = models.JSONField(default=list, help_text="Company titles in English")

    # Location information (denormalized for performance)
    municipality_id = models.IntegerField(
        null=True, blank=True, help_text="Municipality ID"
    )
    municipality_name = models.CharField(
        max_length=255, null=True, blank=True, help_text="Municipality name"
    )
    prefecture_id = models.IntegerField(
        null=True, blank=True, help_text="Prefecture ID"
    )
    prefecture_name = models.CharField(
        max_length=255, null=True, blank=True, help_text="Prefecture name"
    )
    city = models.CharField(max_length=255, null=True, blank=True, help_text="City")
    street = models.CharField(max_length=255, null=True, blank=True, help_text="Street")
    street_number = models.CharField(
        max_length=50, null=True, blank=True, help_text="Street number"
    )
    zip_code = models.CharField(
        max_length=10, null=True, blank=True, help_text="ZIP code"
    )
    po_box = models.CharField(max_length=50, null=True, blank=True, help_text="PO box")

    # Contact information
    url = models.URLField(null=True, blank=True, help_text="Company URL")
    email = models.EmailField(null=True, blank=True, help_text="Company email")

    # Company details (denormalized)
    is_branch = models.BooleanField(
        null=True, blank=True, help_text="Whether this is a branch"
    )
    objective = models.TextField(
        null=True, blank=True, help_text="Company business objective"
    )
    legal_type_id = models.IntegerField(
        null=True, blank=True, help_text="Legal type ID"
    )
    legal_type_name = models.CharField(
        max_length=255, null=True, blank=True, help_text="Legal type name"
    )
    gemi_office_id = models.IntegerField(
        null=True, blank=True, help_text="GEMI office ID"
    )
    gemi_office_name = models.CharField(
        max_length=255, null=True, blank=True, help_text="GEMI office name"
    )

    # Dates and status
    incorporation_date = models.CharField(
        max_length=50, null=True, blank=True, help_text="Incorporation date"
    )
    last_status_change = models.CharField(
        max_length=50, null=True, blank=True, help_text="Last status change date"
    )
    status_id = models.IntegerField(null=True, blank=True, help_text="Status ID")
    status_name = models.CharField(
        max_length=255, null=True, blank=True, help_text="Status name"
    )
    auto_registered = models.BooleanField(
        null=True, blank=True, help_text="Whether the company is auto-registered"
    )

    # Branch GEMI numbers
    branch_gemi_numbers = models.JSONField(
        default=list, help_text="Branch GEMI numbers"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True, help_text="Creation timestamp")
    updated_at = models.DateTimeField(auto_now=True, help_text="Last update timestamp")
    last_updated = models.DateTimeField(
        default=timezone.now, help_text="Last update from GEMI API"
    )

    # PostgreSQL Full-Text Search
    search_vector = SearchVectorField(null=True, blank=True)

    class Meta:
        db_table = "companies"
        indexes = [
            models.Index(fields=["ar_gemi"]),
            models.Index(fields=["afm"]),
            models.Index(fields=["co_name_el"]),
            models.Index(fields=["municipality_id"]),
            models.Index(fields=["prefecture_id"]),
            models.Index(fields=["legal_type_id"]),
            models.Index(fields=["status_id"]),
            models.Index(fields=["last_updated"]),
        ]

    def __str__(self):
        return f"{self.ar_gemi} - {self.co_name_el or 'No name'}"


class CompanyActivity(models.Model):
    """Company activities/business codes."""

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="activities"
    )
    activity_id = models.CharField(max_length=50, help_text="Activity code/ID")
    activity_name = models.TextField(help_text="Activity description")
    activity_type = models.CharField(max_length=100)
    date_from = models.CharField(max_length=50, null=True, blank=True)
    date_to = models.CharField(max_length=50, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "company_activities"
        indexes = [
            models.Index(fields=["company", "activity_id"]),
            models.Index(fields=["activity_id"]),
        ]


class CompanyPerson(models.Model):
    """Persons associated with the company."""

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="persons"
    )
    person_name = models.CharField(max_length=500, null=True, blank=True)
    business_name = models.CharField(max_length=500, null=True, blank=True)
    role = models.CharField(max_length=255, null=True, blank=True)
    date_from = models.CharField(max_length=50, null=True, blank=True)
    date_to = models.CharField(max_length=50, null=True, blank=True)
    is_representative_alone = models.BooleanField(null=True, blank=True)
    is_representative_in_common = models.BooleanField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    # PostgreSQL Full-Text Search
    search_vector = SearchVectorField(null=True, blank=True)

    class Meta:
        db_table = "company_persons"
        indexes = [
            models.Index(fields=["company"]),
            models.Index(fields=["person_name"]),
            models.Index(fields=["role"]),
        ]


class CompanyCapital(models.Model):
    """Company capital information."""

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="capital"
    )
    capital_stock = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )
    currency = models.CharField(max_length=10, null=True, blank=True)
    ecsokefalaiikes = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )
    eggiitikes = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "company_capital"


class CompanyStock(models.Model):
    """Company stock information."""

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="stocks"
    )
    stock_type_id = models.IntegerField(null=True, blank=True)
    amount = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    nominal_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    stock_type = models.CharField(max_length=500, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "company_stocks"
        indexes = [
            models.Index(fields=["company"]),
            models.Index(fields=["stock_type_id"]),
        ]
