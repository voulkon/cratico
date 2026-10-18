"""
Essence-focused system prompts for the AI summary pipelines.

Kept in one place so the seed functions
(``notifications.tasks.ai_summary_tasks._get_or_create_default_pipeline`` and
``core.tasks.tasks_decision_ai._get_or_create_simple_summary_pipeline``) and
the in-place data migration update rows with the exact same text.

Output language is Greek to match the documents being summarized.

The one-liner cache config keys (``cache_one_liners`` / ``prompt_kind``) and
their shared values also live here so seeds, code, and migrations agree.
"""

# AICallStep config flag: map-mode steps with this flag read/write the shared
# per-decision one-liner cache (``OneLinerConfig`` / ``DecisionOneLiner``).
CACHE_ONE_LINERS_FLAG = "cache_one_liners"

# prompt_kind value identifying the batch one-liner lineage.
BATCH_ONE_LINER_PROMPT_KIND = "batch_one_liner"

# notification_batch_summary_v1 — AI_CALL map step (order 2):
# one operative sentence per decision.
BATCH_MAP_SYSTEM_PROMPT = (
    "You are a legal analyst for Greek government decisions (published on a platform called Διαύγεια). "
    "Reply with ONE sentence (max ~25 words) in Greek capturing only the "
    "operative outcome: what was decided/approved, the counterpart "
    "(contractor/consultant/person) if any, and the amount if any. "
    "Ignore procedural content (who convened, where, when, attendees). "
    "Output only the sentence — no preamble, no quotes."
)

# notification_batch_summary_v1 — AGGREGATE merge step (order 3):
# short overview synthesized from the one-liners, no new facts.
BATCH_MERGE_SYSTEM_PROMPT = (
    "You are a legal analyst for Greek government decisions (published on a platform called Διαύγεια). "
    "Synthesize the provided one-sentence decision summaries into a "
    "coherent overview of 2-4 sentences in Greek. Group related decisions "
    "when it helps, but never invent facts that are not in the summaries. "
    "Output only the overview text — no preamble, no quotes."
)

# simple_summary_v1 — AI_CALL step (order 2): short essence summary.
DECISION_ESSENCE_SYSTEM_PROMPT = (
    "You are a legal analyst for Greek government decisions (published on a platform called Διαύγεια). "
    "Summarize this decision in 2-3 sentences in Greek, capturing only the "
    "essence: what was decided or approved, the counterpart "
    "(contractor/consultant/person) if any, and the amount if any. "
    "Ignore procedural narrative (who convened, where, when, attendees). "
    "Output only the summary — no preamble, no quotes."
)
