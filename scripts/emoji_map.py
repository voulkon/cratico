"""
emoji_map.py — Single source of truth for emoji → plain-text replacements.

WHY EMOJIS DON'T BELONG IN PRODUCTION CODE
===========================================

1. Machine-readable log tags
   Log aggregators (ELK / Elasticsearch, Datadog, CloudWatch, Loki, Grafana)
   parse log lines as structured text.  Emojis are opaque Unicode scalars that
   aggregators cannot match, filter, or alert on reliably.  Standardised ASCII
   tags such as [WARN] or [ERROR] are unambiguous tokens that every query
   language can handle with a plain string match or regex.

   Bad : logger.info("🚀 Service started")       # Kibana can't alert on "🚀"
   Good: logger.info("[LAUNCH] Service started")  # trivially filterable

2. Terminal & encoding compatibility
   Emoji rendering depends on the terminal, the font, the locale, and the
   character-set encoding of the process.  Plain ASCII works flawlessly in
   every environment: ancient CI runners, SSH sessions with LC_ALL=C, Windows
   cmd.exe, log-shipping agents that transcode to latin-1, embedded syslog
   daemons — you name it.

PLEASE RESIST THE URGE TO ADD EMOJIS
=====================================
AI coding assistants (and some human developers) have a habit of sprinkling
emojis into log statements, docstrings, and comments to make output "nicer".
Resist it.  Use the bracketed tags below instead — they look just as clear in
any context that actually supports rendering, and they survive every context
that doesn't.

HOW TO USE THIS MAP
===================
- scripts/detect_ai_slop.py  — flags files that contain unmapped emojis.
- scripts/fix_emojis.py      — replaces every emoji in the map with its tag,
                               in-place (use --dry-run first to preview).

To extend coverage:
  1. Add a new entry here (emoji -> "[TAG]").
  2. Run  python scripts/fix_emojis.py --list  to verify the mapping.
  3. Commit emoji_map.py; both scripts pick up the change automatically.
"""

from typing import Dict

EMOJI_MAP: Dict[str, str] = {
    # Success / status markers
    "✅": "[OK]",
    "✓": "[OK]",
    "✗": "[FAIL]",
    "❌": "[ERROR]",
    "❓": "[UNKNOWN]",
    "✨": "[NEW]",
    # Warnings / alerts
    "⚠": "[WARN]",
    "⚡": "[CRIT]",
    "🔥": "[FATAL]",
    "💥": "[CRASH]",
    "🚨": "[ALERT]",
    "🚫": "[DENIED]",
    # Actions / process
    "🚀": "[LAUNCH]",
    "🔄": "[RETRY]",
    "🔍": "[SCAN]",
    "🔎": "[FIND]",
    "🎯": "[TARGET]",
    "🏁": "[END]",
    # Data / documents
    "📄": "[FILE]",
    "📁": "[DIR]",
    "📂": "[DIR_OPEN]",
    "📦": "[PKG]",
    "📊": "[CHART]",
    "📈": "[METRIC]",
    "📋": "[COPY]",
    "📌": "[PIN]",
    "📍": "[LOC]",
    "📎": "[ATTACH]",
    "📏": "[SCALE]",
    "📝": "[NOTE]",
    "📅": "[DATE]",
    "📡": "[REMOTECALL]",
    "📤": "[EXPORT]",
    "📥": "[IMPORT]",
    # Technical / infra
    "🔧": "[CONFIG]",
    "🔌": "[CONN]",
    "🔑": "[AUTH]",
    "🔒": "[SECURE]",
    "🔗": "[LINK]",
    "🔤": "[STR]",
    "🗄": "[DB]",
    "🗑": "[PURGE]",
    "🗓": "[SCHED]",
    "💾": "[SAVE]",
    "💻": "[CLIENT]",
    "🖥": "[SERVER]",
    "🕵": "[AUDIT]",
    # Org / entity icons
    "🏢": "[CORP]",
    "🏥": "[HEALTH]",
    "🏭": "[PROD]",
    "👤": "[USER]",
    "🌐": "[NET]",
    # Misc
    "💡": "[INFO]",
    "💰": "[COST]",
    "💱": "[FX]",
    "💼": "[BIZ]",
    "📆": "[CAL]",
    "🎉": "[EVENT]",
    "🐛": "[BUG]",
    "🧪": "[TEST]",
    "🧹": "[CLEAN]",
    "😞": "[FAIL]",
    "🥇": "[P1]",
    "🥈": "[P2]",
    "🥉": "[P3]",
    "⚙": "[SYS]",
    "⚪": "[PENDING]",
    "🔴": "[STOP]",
    "🔵": "[RUNNING]",
    "🔇": "[MUTE]",
}
