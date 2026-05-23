from django.db import models


class Dictionary(models.Model):
    uid = models.CharField(max_length=255, primary_key=True)
    label = models.CharField(max_length=255)

    class Meta:
        verbose_name_plural = "Dictionaries"

    def __str__(self):
        return self.label


class DictionaryItem(models.Model):
    uid = models.CharField(max_length=255, primary_key=True)
    label = models.CharField(max_length=255)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    dictionary = models.ForeignKey(
        Dictionary, on_delete=models.CASCADE, related_name="items"
    )

    def __str__(self):
        return self.label
