from pathlib import Path

import factory
import pytest
import vcr
from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.models.pipeline import (
    PipelineDefinition,
    PipelineRun,
    PipelineStep,
    PipelineStepRun,
    RunStatus,
    StepType,
)
from core.services.decision_ingestion_service import DecisionIngestionService
from factory.django import DjangoModelFactory


@pytest.fixture
def corrupted_file_name() -> str:
    """Fixture to provide the name of a corrupted file."""
    return "Corrupted_text - 9ΑΦΞ6-ΧΚΗ.pdf"


@pytest.fixture
def another_not_corrupted_file_name() -> str:
    """Fixture to provide the name of another not corrupted file."""
    return "yet_another_with_non_corrupted_text - 9ΧΒΕ46ΜΑΠΣ-ΑΗΗ.pdf"


@pytest.fixture
def not_corrupted_file_name() -> str:
    """Fixture to provide the name of a not corrupted file."""
    return "Not_Corrupted - ΨΑ8Α469Β7Ι-ΤΔΒ.pdf"


@pytest.fixture
def file_path_factory(pdf_for_testing_path):
    """Factory fixture to create file paths with existence checking."""

    def _get_file_path(file_name: str) -> Path:
        the_path = pdf_for_testing_path / Path(file_name)
        if not the_path.exists():
            raise FileNotFoundError(
                f"Test file {the_path} does not exist. "
                "Please ensure it is present in the test directory."
            )
        return the_path

    return _get_file_path


@pytest.fixture
def corrupted_file_path(file_path_factory, corrupted_file_name) -> Path:
    """Fixture to provide the path of a corrupted file."""
    return file_path_factory(corrupted_file_name)


@pytest.fixture
def not_corrupted_file_path(file_path_factory, not_corrupted_file_name) -> Path:
    """Fixture to provide the path of a not corrupted file."""
    return file_path_factory(not_corrupted_file_name)


@pytest.fixture
def another_not_corrupted_file_path(
    file_path_factory, another_not_corrupted_file_name
) -> Path:
    """Fixture to provide the path of a not corrupted file."""
    return file_path_factory(another_not_corrupted_file_name)


# --- VCR Integration Tests ---


@pytest.fixture
def vcr_config():
    """Provide VCR configuration for tests."""
    return vcr.VCR(
        serializer="yaml",
        cassette_library_dir="fixtures/vcr_cassettes",
        record_mode="once",
        match_on=["uri", "method"],
        decode_compressed_response=True,
    )


@pytest.fixture
def daily_decisions_vcr_cassette(vcr_config):
    """Factory fixture to create VCR cassettes."""

    def _create_cassette(cassette_name):
        return vcr_config.use_cassette(cassette_name)

    return _create_cassette


# --- Helper Fixtures ---


@pytest.fixture
def a_test_diavgeia_fetcher() -> DiavgeiaFetcher:
    """Provides a MagicMock for the DiavgeiaFetcher."""
    return DiavgeiaFetcher()


@pytest.fixture
def a_test_decision_service(
    mock_diavgeia_fetcher: DiavgeiaFetcher,
) -> DecisionIngestionService:
    """Provides an instance of the service with a mocked fetcher and zero delay."""
    # Use delay=0 for tests to avoid actual sleeping
    return DecisionIngestionService(mock_diavgeia_fetcher, delay_seconds=20)


# ============================================================================
# Pipeline Model Factories
# ============================================================================


class PipelineDefinitionFactory(DjangoModelFactory):
    """Factory for ``PipelineDefinition``."""

    class Meta:
        model = PipelineDefinition
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"test-pipeline-{n}")
    version = 1
    is_active = True


class PipelineStepFactory(DjangoModelFactory):
    """Factory for ``PipelineStep``."""

    class Meta:
        model = PipelineStep

    pipeline = factory.SubFactory(PipelineDefinitionFactory)
    order = factory.Sequence(lambda n: n)
    step_type = StepType.EXTRACT
    name = factory.LazyAttribute(lambda o: f"Step {o.order}")
    config = factory.LazyFunction(dict)
    is_active = True


class PipelineRunFactory(DjangoModelFactory):
    """Factory for ``PipelineRun``."""

    class Meta:
        model = PipelineRun

    pipeline = factory.SubFactory(PipelineDefinitionFactory)
    status = RunStatus.PENDING
    trigger = "manual"


class PipelineStepRunFactory(DjangoModelFactory):
    """Factory for ``PipelineStepRun``."""

    class Meta:
        model = PipelineStepRun

    run = factory.SubFactory(PipelineRunFactory)
    step = factory.SubFactory(PipelineStepFactory)
    order = factory.LazyAttribute(lambda o: o.step.order if o.step else 0)
    status = RunStatus.PENDING


# ============================================================================
# Pipeline Fixtures
# ============================================================================


@pytest.fixture
def pipeline_definition():
    """A basic pipeline definition with no steps."""
    return PipelineDefinitionFactory()


@pytest.fixture
def pipeline_with_extract_step(pipeline_definition):
    """Pipeline with a single EXTRACT step."""
    PipelineStepFactory(
        pipeline=pipeline_definition,
        order=0,
        step_type=StepType.EXTRACT,
        name="Extract text",
        config={"max_chars": 50000},
    )
    return pipeline_definition


@pytest.fixture
def pipeline_with_all_steps(pipeline_definition):
    """Pipeline with EXTRACT → PREPROCESS → AI_CALL → AGGREGATE."""
    PipelineStepFactory(
        pipeline=pipeline_definition,
        order=0,
        step_type=StepType.EXTRACT,
        name="Extract text",
    )
    PipelineStepFactory(
        pipeline=pipeline_definition,
        order=1,
        step_type=StepType.PREPROCESS,
        name="Strip boilerplate",
        config={"preprocessor": "regex_strip"},
    )
    PipelineStepFactory(
        pipeline=pipeline_definition,
        order=2,
        step_type=StepType.AI_CALL,
        name="Summarize each decision",
        config={
            "provider": "OPENROUTER",
            "model": "test/model",
            "prompt_template": "Summarize: {{ text }}",
            "system_prompt": "You are helpful.",
        },
    )
    PipelineStepFactory(
        pipeline=pipeline_definition,
        order=3,
        step_type=StepType.AGGREGATE,
        name="Merge summaries",
        config={"strategy": "concat"},
    )
    return pipeline_definition


@pytest.fixture
def decisions_plain():
    """Return a list of plain-dict decisions used as pipeline input."""
    return [
        {"id": "ADA000001", "text": "Decision one content."},
        {"id": "ADA000002", "text": "Decision two content."},
        {"id": "ADA000003", "text": "Decision three content."},
    ]


@pytest.fixture
def decisions_with_raw_text():
    """Decisions as dicts with ``raw_text`` for ExtractStep."""
    return [
        {"id": "ADA000001", "raw_text": "Full text of decision one."},
        {"id": "ADA000002", "raw_text": "Full text of decision two with ΔΙΑΒΓΕΙΑ - header."},
    ]
