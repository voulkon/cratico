from django.contrib.postgres.search import SearchVectorField
from django.db import models


class OrganizationStatus(models.TextChoices):
    """Κατάσταση φορέα."""

    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    PENDING = "pending", "Pending"


class UnitDescendants(models.TextChoices):
    """Επίπεδο επιστροφής μονάδων."""

    CHILDREN = "children", "Children"
    ALL = "all", "All"


class UnitStatus(models.TextChoices):
    """Κατάσταση μονάδων."""

    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    ALL = "all", "All"


class Organization(models.Model):
    """Represents a single organization."""

    uid = models.CharField(max_length=255, primary_key=True)
    latin_name = models.CharField(max_length=255)
    abbreviation = models.CharField(max_length=100, blank=True, null=True)
    label = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=OrganizationStatus.choices,
        default=OrganizationStatus.ACTIVE,
    )
    category = models.CharField(max_length=255)
    vat_number = models.CharField(max_length=50, blank=True, null=True)
    fek_number = models.CharField(max_length=50, blank=True, null=True)
    fek_issue = models.CharField(max_length=50, blank=True, null=True)
    fek_year = models.CharField(max_length=4, blank=True, null=True)
    website = models.CharField(max_length=255, blank=True, null=True)
    supervisor_org_uid = models.CharField(max_length=255, blank=True, null=True)
    supervisor_org_name = models.CharField(max_length=255, blank=True, null=True)

    # PostgreSQL Full-Text Search
    search_vector = SearchVectorField(null=True, blank=True)

    def __str__(self):
        return self.label


class OrganizationDomain(models.Model):
    """Domain for an organization."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="domains"
    )
    domain = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.organization.label} - {self.domain}"


class Unit(models.Model):
    """Represents a single organizational unit."""

    uid = models.CharField(max_length=255, primary_key=True)
    label = models.CharField(max_length=255)
    active = models.BooleanField(default=True)
    active_from = models.DateTimeField(null=True, blank=True)
    active_until = models.DateTimeField(null=True, blank=True)
    category = models.CharField(max_length=255)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="units"
    )
    resolution_path = models.JSONField(
        null=True,
        blank=True,
        help_text="Tracks how organization was resolved if not directly specified",
    )

    # PostgreSQL Full-Text Search
    search_vector = SearchVectorField(null=True, blank=True)

    def __str__(self):
        return self.label


class UnitDomain(models.Model):
    """Domain for a unit."""

    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="domains")
    domain = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.unit.label} - {self.domain}"


class Position(models.Model):
    """Represents a single organizational position."""

    uid = models.CharField(max_length=255, primary_key=True)
    label = models.CharField(max_length=255)

    def __str__(self):
        return self.label


class Signer(models.Model):
    """Represents a single signer."""

    uid = models.CharField(max_length=255, primary_key=True)
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    active = models.BooleanField(default=True)
    active_from = models.DateTimeField(null=True, blank=True)
    active_until = models.DateTimeField(null=True, blank=True)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="signers"
    )
    has_organization_sign_rights = models.BooleanField(default=False)
    resolution_path = models.JSONField(
        null=True,
        blank=True,
        help_text="Tracks how organization was resolved if not directly specified",
    )

    # PostgreSQL Full-Text Search
    search_vector = SearchVectorField(null=True, blank=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class SignerUnit(models.Model):
    """Represents a unit associated with a signer."""

    signer = models.ForeignKey(Signer, on_delete=models.CASCADE, related_name="units")
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE)
    position = models.ForeignKey(Position, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.signer} - {self.unit.label} ({self.position.label})"

    class Meta:
        unique_together = ("signer", "unit", "position")


class OrganizationGeoData(models.Model):
    """Stores geographical data for an organization from Nominatim."""

    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="geodata",
    )
    place_id = models.BigIntegerField(null=True, blank=True)  # Nominatim's place_id
    lat = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    lon = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    category = models.CharField(max_length=100, blank=True, null=True)
    type = models.CharField(max_length=100, blank=True, null=True)
    place_rank = models.IntegerField(null=True, blank=True)
    importance = models.FloatField(null=True, blank=True)
    addresstype = models.CharField(max_length=100, blank=True, null=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    display_name = models.TextField(blank=True, null=True)
    boundingbox = models.JSONField(null=True, blank=True)  # Store as list of strings
    geojson = models.JSONField(null=True, blank=True)  # Store the GeoJSON object
    fetched_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"GeoData for {self.organization.label}"

    class Meta:
        verbose_name = "Organization Geo Data"
        verbose_name_plural = "Organization Geo Data"
