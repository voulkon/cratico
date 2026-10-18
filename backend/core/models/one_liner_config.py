"""
OneLinerConfig — the shareable generation circumstances of a one-liner.

A tiny lookup table: one row per distinct (prompt_kind, system_prompt,
prompt_template, provider, model, temperature, max_tokens) combination.
``DecisionOneLiner`` rows reference a config, so "provider A vs provider B"
or "prompt v1 vs prompt v2" comparisons read the circumstances straight from
the columns — no decoding of any hash.

The ``key`` column (sha256 of the canonical column values) exists ONLY as the
uniqueness backstop / fast equality check — Postgres btree cannot safely
unique-index long TextFields.  It is never displayed or used for judgment.
"""

import hashlib
import json
from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _


def one_liner_config_key(
    prompt_kind,
    system_prompt,
    prompt_template,
    provider,
    model,
    temperature,
    max_tokens,
):
    """Build the compact uniqueness key from the config's own columns.

    Pure function of the columns, normalized (temperature quantized to the
    field's scale, ``max_tokens`` ``None``-aware) so equal circumstances always
    produce the same key.
    """
    quantized = Decimal(str(temperature or 0)).quantize(Decimal("0.01"))
    payload = {
        "prompt_kind": prompt_kind or "",
        "system_prompt": system_prompt or "",
        "prompt_template": prompt_template or "",
        "provider": provider or "",
        "model": model or "",
        "temperature": str(quantized),
        "max_tokens": int(max_tokens) if max_tokens is not None else None,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class OneLinerConfig(models.Model):
    """Shareable LLM generation circumstances for one-liner attempts."""

    prompt_kind = models.CharField(
        max_length=50,
        db_index=True,
        help_text=_("Lineage slug, e.g. 'batch_one_liner'."),
    )
    system_prompt = models.TextField()
    prompt_template = models.TextField()
    provider = models.CharField(max_length=30, default="OPENROUTER")
    model = models.CharField(max_length=200)
    temperature = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=Decimal("0.30"),
        help_text=_("Exact-equality cache dimension (no float wobble)."),
    )
    max_tokens = models.IntegerField(null=True, blank=True)

    # Compact derived equality backstop — never for display (see module doc).
    key = models.CharField(max_length=64, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("One Liner Config")
        verbose_name_plural = _("One Liner Configs")

    def __str__(self):
        return f"{self.prompt_kind} · {self.provider}/{self.model}"

    @classmethod
    def get_or_create_for(
        cls,
        prompt_kind,
        system_prompt,
        prompt_template,
        provider,
        model,
        temperature,
        max_tokens,
    ):
        """Race-safe column-equality lookup (``get_or_create`` via ``key``)."""
        key = one_liner_config_key(
            prompt_kind=prompt_kind,
            system_prompt=system_prompt,
            prompt_template=prompt_template,
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return cls.objects.get_or_create(
            key=key,
            defaults={
                "prompt_kind": prompt_kind or "",
                "system_prompt": system_prompt or "",
                "prompt_template": prompt_template or "",
                "provider": provider or "",
                "model": model or "",
                "temperature": Decimal(str(temperature or 0)).quantize(
                    Decimal("0.01")
                ),
                "max_tokens": int(max_tokens) if max_tokens is not None else None,
            },
        )[0]
