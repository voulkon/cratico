from __future__ import annotations

from typing import Any, Iterable, Mapping

from django.db import models, transaction
from loguru import logger


class BaseImporter:
    """
    Reusable 'update_or_create many' helper.

    Subclasses declare:
        model          – Django model class
        uid_field      – name of the unique key attr on the DTO
        field_map      – {dto_attr: model_field}
        do_not_update_fields – optional list of fields to exclude from updates
    """

    # override in subclasses ↓↓↓
    model: type[models.Model]
    uid_field: str = "uid"
    field_map: Mapping[str, str] = {}
    do_not_update_fields: list[str] = []  # Fields to never update (e.g., created_at)
    # Fields handled specially (e.g., relations) and not via direct mapping
    # Useful to exclude them during default mapping process
    special_handling_fields: list[str] = []

    def _model_field_names(self) -> set[str]:
        """
        Return all forward model fields, including FKs.
        Uses ._meta.fields to skip reverse relations automatically.
        """
        return {f.name for f in self.model._meta.fields}

    def _to_defaults(self, dto) -> dict[str, Any]:
        """
        Convert dto -> {model_field: value} applying field_map.
        Focuses on direct mappings and simple transformations.
        Excludes UID field and fields marked for special handling.
        """
        model_fields = self._model_field_names()
        updateable_fields = model_fields - set(self.do_not_update_fields)
        defaults = {}

        # Use Pydantic's recommended way to get data dictionary
        if hasattr(dto, "model_dump"):
            # dto_data = dto.model_dump(exclude_unset=True)  # Pydantic v2+
            dto_data = dto.model_dump()  # Pydantic v2+
        elif hasattr(dto, "dict"):
            dto_data = dto.dict(exclude_unset=True)  # Pydantic v1
        else:
            # Basic fallback (less robust)
            dto_data = {k: v for k, v in dto.__dict__.items() if not k.startswith("_")}

        # Exclude UID field and specially handled fields from direct mapping
        fields_to_skip = {self.uid_field} | set(self.special_handling_fields)

        for dto_attr, value in dto_data.items():
            if dto_attr in fields_to_skip:
                continue

            model_field = self.field_map.get(dto_attr, dto_attr)

            if model_field in updateable_fields:
                defaults[model_field] = value
            # else:
            # logger.trace(f"Skipping unmapped/reverse field: {dto_attr} -> {model_field}")

        return defaults

    @transaction.atomic
    def import_many(self, dtos: Iterable, *, defaults=None) -> int:
        defaults = defaults or {}
        total = 0
        for i, (dto) in enumerate(dtos):
            if i % 50 == 0:
                logger.debug(f"Processing item number {i}...")
                percentage_done = (i / len(dtos)) * 100
                logger.debug(f"Progress: {percentage_done:.2f}%")
            mapped = self._to_defaults(dto)
            # merge in extra defaults (e.g. dictionary instance):
            combined = {**mapped, **defaults}

            # **ADD DEBUG LOGGING HERE**
            if hasattr(dto, "uid"):
                logger.debug(f"Unit {dto.uid} combined fields: {list(combined.keys())}")
                if "parent_id" in combined:
                    logger.debug(f"Unit {dto.uid} parent_id: {combined['parent_id']}")
                if "organization_id" in combined:
                    logger.debug(
                        f"Unit {dto.uid} organization_id: {combined['organization_id']}"
                    )

            lookup = {self.uid_field: getattr(dto, self.uid_field)}
            obj, created = self.model.objects.update_or_create(
                **lookup, defaults=combined
            )
            total += int(created)
        return total
