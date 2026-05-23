from django.db import models
from django.db.models import JSONField


class ActType(models.Model):
    """Django model representing an act type."""

    uid = models.CharField(max_length=255, primary_key=True)
    label = models.CharField(max_length=255)
    allowed_in_decisions = models.BooleanField(default=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="child_types",
    )

    def __str__(self):
        return self.label

    class Meta:
        verbose_name = "Act Type"
        verbose_name_plural = "Act Types"


class ExtraFieldType(models.TextChoices):
    """Field types for extra fields in act types."""

    STRING = "string", "String"
    NUMBER = "number", "Number"
    INTEGER = "integer", "Integer"
    BOOLEAN = "boolean", "Boolean"
    OBJECT = "object", "Object"
    DATE = "date", "Date"
    MONETARY = "monetary", "Monetary"


class ExtraField(models.Model):
    """Django model representing an extra field for an act type."""

    uid = models.CharField(max_length=255)
    act_type = models.ForeignKey(
        ActType, on_delete=models.CASCADE, related_name="extra_fields"
    )
    label = models.CharField(max_length=255, null=True, blank=True)
    field_type = models.CharField(
        max_length=50,
        choices=ExtraFieldType.choices,
        null=True,
        blank=True,
    )
    validation = models.CharField(max_length=255, null=True, blank=True)
    required = models.BooleanField(default=False)
    multiple = models.BooleanField(default=False)
    max_length = models.IntegerField(default=0)
    dictionary = models.CharField(max_length=255, null=True, blank=True)
    search_term = models.CharField(max_length=255, null=True, blank=True)
    rel_ada_decision_types = JSONField(null=True, blank=True)
    rel_ada_constrained_in_organization = models.BooleanField(null=True, blank=True)
    fixed_value_list = JSONField(null=True, blank=True)
    parent_field = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="nested_fields",
    )

    def __str__(self):
        label = self.label or self.uid
        return f"{label} ({self.act_type.label})"

    class Meta:
        verbose_name = "Extra Field"
        verbose_name_plural = "Extra Fields"
        unique_together = ("uid", "act_type")
        ordering = ["act_type", "uid"]


class ActTypeHelp(models.Model):
    """Help text associated with act types."""

    act_type = models.OneToOneField(
        ActType, on_delete=models.CASCADE, related_name="help_text"
    )
    content = models.TextField()

    def __str__(self):
        return f"Help for {self.act_type.label}"

    class Meta:
        verbose_name = "Act Type Help"
        verbose_name_plural = "Act Type Help"
