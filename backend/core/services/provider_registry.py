class ProviderRegistry:
    """Registry for document processing providers"""

    _extractors = {}
    _analyzers = {}
    _embedders = {}

    @classmethod
    def register_extractor(cls, provider_name, extractor_class):
        """Register a text extraction provider"""
        cls._extractors[provider_name] = extractor_class

    @classmethod
    def register_analyzer(cls, provider_name, analyzer_class):
        """Register an analysis provider"""
        cls._analyzers[provider_name] = analyzer_class

    @classmethod
    def register_embedder(cls, provider_name, embedder_class):
        """Register an embedding provider"""
        cls._embedders[provider_name] = embedder_class

    @classmethod
    def get_extractor(cls, provider_name=None):
        """Get extractor by provider name"""
        if provider_name is None:
            # Get default provider from settings
            from django.conf import settings

            provider_name = getattr(
                settings, "DEFAULT_TEXT_EXTRACTION_PROVIDER", "PYPDF"
            )

        extractor_class = cls._extractors.get(provider_name)
        if not extractor_class:
            raise ValueError(f"No extractor registered for provider: {provider_name}")

        return extractor_class()

    # Similar methods for analyzers and embedders


# # Usage in other modules:
# from core.services.provider_registry import ProviderRegistry

# # Register providers
# ProviderRegistry.register_extractor("PYPDF", PyPdfExtractor)
# ProviderRegistry.register_extractor("TESSERACT", TesseractExtractor)

# # Get provider instance
# extractor = ProviderRegistry.get_extractor("PYPDF")
