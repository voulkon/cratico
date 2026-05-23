import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Check the current diavgeia-api package models and capabilities"

    def handle(self, *args, **options):
        try:
            # Import the models
            from diavgeia_api.models.decisions import AmountWithKAE, ExtraFieldValues

            self.stdout.write("[OK] Successfully imported diavgeia-api models")

            # Check ExtraFieldValues
            self.stdout.write(f"\n[COPY] ExtraFieldValues model:")
            self.stdout.write(f"   Type: {type(ExtraFieldValues)}")

            # Check if it's Pydantic v1 or v2
            try:
                # Pydantic v2 check
                if hasattr(ExtraFieldValues, "model_config"):
                    config = ExtraFieldValues.model_config
                    self.stdout.write(f"   [OK] Pydantic v2 - model_config: {config}")
                    if hasattr(config, "extra") or "extra" in config:
                        self.stdout.write(
                            f"   [TARGET] Extra fields setting: {getattr(config, 'extra', config.get('extra', 'Not set'))}"
                        )
                    else:
                        self.stdout.write(
                            f"   [ERROR] No 'extra' setting in model_config"
                        )
                else:
                    self.stdout.write(
                        f"   [ERROR] No model_config found (might be Pydantic v1)"
                    )

                # Pydantic v1 check
                if hasattr(ExtraFieldValues, "__config__"):
                    config = ExtraFieldValues.__config__
                    self.stdout.write(f"   [COPY] Pydantic v1 Config class found")
                    if hasattr(config, "extra"):
                        self.stdout.write(
                            f"   [TARGET] Extra fields setting: {config.extra}"
                        )
                    else:
                        self.stdout.write(f"   [ERROR] No 'extra' setting in Config")

            except Exception as e:
                self.stdout.write(f"   [ERROR] Error checking config: {e}")

            # Check fields - Fixed for Pydantic v2
            self.stdout.write(f"\n[COPY] ExtraFieldValues fields:")
            if hasattr(ExtraFieldValues, "model_fields"):
                # Pydantic v2
                fields = ExtraFieldValues.model_fields
                for name, field in fields.items():
                    # Get the annotation safely
                    annotation = getattr(field, "annotation", "Unknown")
                    self.stdout.write(f"   • {name}: {annotation}")
            elif hasattr(ExtraFieldValues, "__fields__"):
                # Pydantic v1
                fields = ExtraFieldValues.__fields__
                for name, field in fields.items():
                    self.stdout.write(f"   • {name}: {field.type_}")
            else:
                self.stdout.write(f"   [ERROR] Cannot determine fields")

            # Test creating an instance with unknown fields
            self.stdout.write(f"\n[TEST] Testing unknown field handling:")
            try:
                # Try to create with a known field + unknown field
                test_data = {
                    "financialYear": 2025,
                    "documentType": "ΠΡΑΞΗ",
                    "unknownField": "test_value",  # This should be captured if extra='allow'
                    "sponsorAFMName": {"afm": "123456789", "name": "Test Org"},
                }

                instance = ExtraFieldValues(**test_data)
                self.stdout.write(
                    f"   [OK] Successfully created instance with unknown fields"
                )

                # Check what was captured
                if hasattr(instance, "model_dump"):
                    # Pydantic v2
                    dumped = instance.model_dump()
                    self.stdout.write(f"   [CHART] model_dump() result:")
                    self.stdout.write(json.dumps(dumped, indent=4, ensure_ascii=False))
                elif hasattr(instance, "dict"):
                    # Pydantic v1
                    dumped = instance.dict()
                    self.stdout.write(f"   [CHART] dict() result:")
                    self.stdout.write(json.dumps(dumped, indent=4, ensure_ascii=False))

                # Check for __pydantic_extra__ (v2)
                if hasattr(instance, "__pydantic_extra__"):
                    self.stdout.write(
                        f"   [TARGET] __pydantic_extra__: {instance.__pydantic_extra__}"
                    )

            except Exception as e:
                self.stdout.write(
                    f"   [ERROR] Failed to create instance with unknown fields: {e}"
                )

                # Try with only known fields
                try:
                    known_data = {"financialYear": 2025, "documentType": "ΠΡΑΞΗ"}
                    instance = ExtraFieldValues(**known_data)
                    self.stdout.write(f"   [OK] Can create with known fields only")
                except Exception as e2:
                    self.stdout.write(f"   [ERROR] Even known fields fail: {e2}")

            # Check AmountWithKAE - Fixed for Pydantic v2
            self.stdout.write(f"\n[COPY] AmountWithKAE model:")
            self.stdout.write(f"   Type: {type(AmountWithKAE)}")

            if hasattr(AmountWithKAE, "model_fields"):
                # Pydantic v2
                fields = AmountWithKAE.model_fields
                self.stdout.write(f"   Fields (v2):")
                for name, field in fields.items():
                    annotation = getattr(field, "annotation", "Unknown")
                    self.stdout.write(f"   • {name}: {annotation}")
            elif hasattr(AmountWithKAE, "__fields__"):
                # Pydantic v1
                fields = AmountWithKAE.__fields__
                self.stdout.write(f"   Fields (v1):")
                for name, field in fields.items():
                    self.stdout.write(f"   • {name}: {field.type_}")

            # Check if sponsorAFMName field exists
            has_sponsor_field = (
                hasattr(AmountWithKAE, "__fields__")
                and "sponsorAFMName" in AmountWithKAE.__fields__
            ) or (
                hasattr(AmountWithKAE, "model_fields")
                and "sponsorAFMName" in AmountWithKAE.model_fields
            )

            if has_sponsor_field:
                self.stdout.write(f"   [OK] sponsorAFMName field found!")
            else:
                self.stdout.write(
                    f"   [ERROR] sponsorAFMName field NOT found - model needs updating"
                )

            # Test AmountWithKAE with sponsorAFMName
            self.stdout.write(f"\n[TEST] Testing AmountWithKAE with sponsorAFMName:")
            try:
                kae_test_data = {
                    "kae": "0879Α",
                    "amountWithVAT": 36704.01,
                    "sponsorAFMName": {
                        "afm": "999233404",
                        "afmType": "EL",
                        "afmCountry": "EL",
                        "name": "ΓΕΝΙΚΟ ΝΟΣΟΚΟΜΕΙΟ ΠΕΙΡΑΙΑ ΤΖΑΝΕΙΟ",
                    },
                }

                kae_instance = AmountWithKAE(**kae_test_data)
                self.stdout.write(
                    f"   [OK] Successfully created AmountWithKAE with sponsorAFMName"
                )

                if hasattr(kae_instance, "model_dump"):
                    dumped = kae_instance.model_dump()
                    self.stdout.write(f"   [CHART] AmountWithKAE model_dump():")
                    self.stdout.write(json.dumps(dumped, indent=4, ensure_ascii=False))

            except Exception as e:
                self.stdout.write(
                    f"   [ERROR] Failed to create AmountWithKAE with sponsorAFMName: {e}"
                )

        except ImportError as e:
            self.stdout.write(f"[ERROR] Failed to import diavgeia-api models: {e}")

        # Check package version/location
        try:
            import diavgeia_api

            self.stdout.write(f"\n[PKG] Package info:")
            self.stdout.write(f"   Location: {diavgeia_api.__file__}")
            if hasattr(diavgeia_api, "__version__"):
                self.stdout.write(f"   Version: {diavgeia_api.__version__}")
        except Exception as e:
            self.stdout.write(f"[ERROR] Cannot get package info: {e}")
