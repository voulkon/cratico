"""
PreprocessStep — applies a registered preprocessor to the current text.

Config:
    preprocessor: "noop" (default) — registry key
    params: {} — preprocessor-specific params
"""

from core.models.pipeline import PipelineStepRun
from core.services.pipeline_engine import PipelineContext
from loguru import logger


class PreprocessStep:
    """Applies a text preprocessor to each item in the context."""

    def execute(self, step, step_run: PipelineStepRun, context: PipelineContext, run):
        from core.services.preprocessors.registry import PreprocessorRegistry

        config = step.config or {}
        preprocessor_name = config.get("preprocessor", "noop")
        params = config.get("params", {})

        func = PreprocessorRegistry.get(preprocessor_name)

        processed = {}
        for item_id, text in context.per_item_outputs.items():
            processed[item_id] = func(text, params)

        context.per_item_outputs = processed
        output = "\n---\n".join(processed.values())
        context.steps_output[step.order] = output

        step_run.input_preview = (output or "")[:2000]
        step_run.output_text = (output or "")[:2000]
        step_run.save()

        logger.info(f"PreprocessStep: applied '{preprocessor_name}' to {len(processed)} items")
