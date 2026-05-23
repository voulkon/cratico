import html
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.pydantic_models.text_preprocessing import (
    CorruptionDetectionStrategy,
    PreprocessingResult,
)
from loguru import logger


class TextPreprocessor:
    def __init__(
        self,
        strategy: CorruptionDetectionStrategy = CorruptionDetectionStrategy.COMMON_WORDS,
        dictionary_path: Optional[Path] = None,
        char_validity_threshold: float = 0.7,
        detection_ratio_threshold: float = 0.05,  # Deprecated, kept for compatibility
        coverage_ratio_threshold: float = 0.04,  # % of text words that must be recognizable (5% - lowered for technical documents)
        verbose: bool = False,
    ):

        self.char_validity_threshold = char_validity_threshold
        self.detection_ratio_threshold = detection_ratio_threshold
        self.verbose = verbose
        self.coverage_ratio_threshold = coverage_ratio_threshold

        # Load Greek stopwords - domain-specific terms from Greek government decisions
        self.greek_stopwords: Set[str] = {
            # Government/Institutional
            "ΕΛΛΗΝΙΚΗ ΔΗΜΟΚΡΑΤΙΑ",
            "ΥΠΟΥΡΓΕΙΟ",
            "ΔΙΟΙΚΗΣΗ",
            "ΚΥΒΕΡΝΗΣΗ",
            "ΠΡΩΘΥΠΟΥΡΓΟΣ",
            "ΥΠΟΥΡΓΟΣ",
            "ΓΕΝΙΚΟΣ ΓΡΑΜΜΑΤΕΑΣ",
            "ΔΙΕΥΘΥΝΤΗΣ",
            "ΠΡΟΪΣΤΑΜΕΝΟΣ",
            "ΔΗΜΟΣΙΑ ΔΙΟΙΚΗΣΗ",
            "ΔΗΜΟΣΙΟΣ ΤΟΜΕΑΣ",
            "ΟΡΓΑΝΙΣΜΟΣ",
            "ΥΠΗΡΕΣΙΑ",
            "ΦΟΡΕΑΣ",
            "ΠΑΝΕΠΙΣΤΗΜΙΟ",
            "ΝΟΜΑΡΧΙΑ",
            "ΠΕΡΙΦΕΡΕΙΑ",
            # Legal/Regulatory
            "ΑΠΟΦΑΣΗ",
            "ΝΟΜΟΣ",
            "ΑΡΘΡΟ",
            "ΠΑΡΑΓΡΑΦΟΣ",
            "ΔΙΑΤΑΞΗ",
            "ΠΡΟΕΔΡΙΚΟ ΔΙΑΤΑΓΜΑ",
            "ΕΓΚΥΚΛΙΟΣ",
            "ΚΑΝΟΝΙΣΜΟΣ",
            "ΟΔΗΓΙΑ",
            "ΣΥΜΒΑΣΗ",
            # Financial/Administrative
            "ΧΡΗΜΑΤΙΚΟ",
            "ΕΝΤΑΛΜΑ",
            "ΠΛΗΡΩΜΗ",
            "ΠΡΟΠΛΗΡΩΜΗ",
            "ΔΑΠΑΝΗ",
            "ΕΣΟΔΟ",
            "ΠΡΟΫΠΟΛΟΓΙΣΜΟΣ",
            "ΛΟΓΙΣΤΗΡΙΟ",
            "ΟΙΚΟΝΟΜΙΚΗΣ",
            "ΔΙΑΧΕΙΡΙΣΗΣ",
            "ΤΡΑΠΕΖΑ",
            "ΛΟΓΑΡΙΑΣΜΟΣ",
            "ΕΠΙΤΑΓΗ",
            "ΔΙΚΑΙΟΥΧΟΣ",
            "ΚΡΑΤΗΣΕΙΣ",
            "ΒΕΒΑΙΩΣΗ",
            # Administrative Actions
            "ΕΚΔΟΣΗ",
            "ΑΙΤΙΟΛΟΓΙΑ",
            "ΣΥΝΗΜΜΕΝΑ",
            "ΘΕΣΣΑΛΟΝΙΚΗ",
            "ΑΘΗΝΑ",
            "ΗΜΕΡΟΜΗΝΙΑ",
            "ΕΤΟΣ",
            "ΑΡΙΘΜΟΣ",
            "ΚΑΤΑΣΤΑΣΗ",
            "ΕΚΔΩΣΑΣ",
            "ΥΠΟΓΡΑΦΗ",
            "ΠΡΩΤΟΚΟΛΛΟ",
            "ΠΡΟΙΣΤΑΜΕΝΟΣ",
            "ΔΙΕΥΘΥΝΤΗΣ",
            "ΑΔΑ",
        }
        # Greek legal citation patterns (regex patterns for detection)
        self.legal_citation_patterns = [
            r"[νΝ]\.\s*\d{4}/\d{2,4}",  # ν.4270/14, Ν.4607/2019
            r"[αΑ]ρθρ\.\s*\d+",  # αρθρ.31, Αρθρ.58
            r"[πΠ]αρ\.\s*[αβγδεά]",  # παρ.α΄, Παρ.β
            r"[πΠ]ερ\.\s*[αβγδεά]",  # περ.α΄
            r"ΑΔΑ:\s*[Α-Ω0-9-]+",  # ΑΔΑ: 909Ο469Β7Ι-ΖΨ9
            r"Α\.Φ\.Μ\.\s*\d+",  # Α.Φ.Μ. 038506796
        ]

        self.administrative_indicators = {
            # Official codes/references
            "ΑΔΑ",
            "ΑΦΜ",
            "ΔΟΥ",
            "ΑΜΚΑ",
            "ΑΜ",
            "ΚΑΕ",
            "ΦΕΚ",
            "ΦΠΑ",
            "ΙΚΑ",
            "ΕΦΚΑ",
            # Organizational structure
            "ΔΙΕΥΘΥΝΣΗ",
            "ΤΜΗΜΑ",
            "ΓΡΑΦΕΙΟ",
            "ΥΠΗΡΕΣΙΑ",
            "ΠΡΟΪΣΤΑΜΕΝΟΣ",
            "ΥΠΕΥΘΥΝΟΣ",
            "ΥΠΑΛΛΗΛΟΣ",
            "ΣΥΜΒΟΥΛΙΟ",
            "ΕΠΙΤΡΟΠΗ",
            "ΟΜΑΔΑ",
            # Financial terms
            "ΕΝΤΑΛΜΑ",
            "ΕΠΙΤΑΓΗ",
            "ΛΟΓΑΡΙΑΣΜΟΣ",
            "ΤΡΑΠΕΖΑ",
            "ΠΛΗΡΩΜΗ",
            "ΠΛΗΡΩΜΗΣ",
            "ΠΡΟΠΛΗΡΩΜΗ",
            "ΕΞΟΦΛΗΣΗ",
            "ΔΑΠΑΝΗ",
            "ΕΣΟΔΟ",
            "ΚΡΑΤΗΣΗ",
            "ΚΡΑΤΗΣΕΙΣ",
            "ΔΙΚΑΙΟΥΧΟΣ",
            "ΟΙΚΟΝΟΜΙΚ",
            "ΛΟΓΙΣΤΗΡΙ",
            "ΧΡΗΜΑΤΙΚ",
            # Legal/regulatory markers
            "ΑΠΟΦΑΣΗ",
            "ΒΕΒΑΙΩΣΗ",
            "ΠΡΩΤΟΚΟΛΛΟ",
            "ΕΓΚΡΙΣΗ",
            "ΕΓΚΥΚΛΙΟΣ",
            "ΟΔΗΓΙΑ",
            "ΣΥΜΒΑΣΗ",
            "ΣΥΜΦΩΝΗΤΙΚΟ",
            "ΠΡΑΚΤΙΚΑ",
            # Dates and identifiers
            "ΗΜΕΡΟΜΗΝΙΑ",
            "ΗΜΝΙΑ",
            "ΕΤΟΣ",
            "ΑΡΙΘΜΟΣ",
            "ΠΡΩΤΟΚΟΛΛΟ",
            "ΕΚΔΟΣΗ",
            "ΛΗΞΗ",
            # Common abbreviations in legal citations
            "ν.",
            "Ν.",
            "αρθρ.",
            "Αρθρ.",
            "παρ.",
            "Παρ.",
            "περ.",
            "Περ.",
            "εδ.",
            "Εδ.",
            "κεφ.",
            "Κεφ.",
        }

        # Pattern to identify Greek characters, numbers, basic punctuation, and whitespace
        # Includes: Greek letters, diacritics (΄ͺ), Latin letters (for acronyms/codes),
        # common punctuation, markdown symbols (#), and HTML/formatting chars (<>)
        self.valid_greek_char_pattern = re.compile(
            r"^[Α-ΩΆΈΉΊΌΎΏΪΫα-ωάέήίόύώϊϋΐΰ"
            r"a-zA-Z"  # Latin letters for acronyms, codes
            r"\s\d"  # Whitespace and digits
            r"\.,;:?!€()%/\"\'\«\»\-"  # Punctuation
            r"#<>@&*+=_~`\[\]\{\}\|\\΄ͺ"  # Additional symbols, tonos, dialytika
            r"]+$"
        )

        # Most common Greek words (lowercase only for efficiency)
        self.common_greek_words = {
            "και",
            "που",
            "για",
            "στο",
            "στη",
            "στην",
            "των",
            "του",
            "της",
            "με",
            "από",
            "αυτό",
            "αυτή",
            "αυτός",
            "είναι",
            "δεν",
            "θα",
            "να",
            "ο",
            "η",
            "το",
            "τα",
            "οι",
            "τις",
            "τους",
            "κατά",
            "προς",
            "μετά",
            "πριν",
            "ενώ",
            "όταν",
            "εάν",
            "αν",
            "ή",
            "αλλά",
            "όμως",
            "ώστε",
            "διότι",
            "επειδή",
            "μόνο",
            "πάντα",
            "ακόμη",
            "ακόμα",
            "όλα",
            "όλες",
            "όλους",
            "πολύ",
            "πολλά",
            "πολλές",
            "πολλοί",
            "μια",
            "ένα",
            "ένας",
            "μία",
            "έχει",
            "έχουν",
            "έχω",
            "έχεις",
            "είχε",
            "είχαν",
            "ήταν",
            "ήσαν",
            "πως",
            "ότι",
            "τι",
            "ποιος",
            "ποια",
            "ποιο",
            "πού",
            "πότε",
            "γιατί",
        }

        # Initialize strategy-specific components
        self.strategy = strategy
        self.greek_dictionary: Optional[Set[str]] = None
        self.gr_nlp_pipeline = None
        self.performance_stats: Dict[str, float] = {}

        self._initialize_strategy(dictionary_path)

    def _initialize_strategy(self, dictionary_path: Optional[Path]):
        """Initialize the selected corruption detection strategy."""
        try:
            if self.strategy in [
                CorruptionDetectionStrategy.GREEK_DICTIONARY,
                CorruptionDetectionStrategy.HYBRID,
            ]:
                self.greek_dictionary = self._load_greek_dictionary(dictionary_path)

            if self.strategy in [
                CorruptionDetectionStrategy.GR_NLP_TOOLKIT,
                CorruptionDetectionStrategy.HYBRID,
            ]:
                self._initialize_gr_nlp_toolkit()

        except Exception as e:
            logger.warning(f"Failed to initialize strategy {self.strategy}: {e}")
            logger.info("Falling back to common words strategy")
            self.strategy = CorruptionDetectionStrategy.COMMON_WORDS

    def _detect_legal_citations(self, text: str) -> List[str]:
        """Detect Greek legal citations like ν.4270/14, αρθρ.31, etc."""
        citations = []
        for pattern in self.legal_citation_patterns:
            matches = re.findall(pattern, text)
            citations.extend(matches)
        return citations

    def _load_greek_dictionary(self, dictionary_path: Optional[Path]) -> Set[str]:
        """Load Greek dictionary from JSON file."""
        if dictionary_path and dictionary_path.exists():
            path_to_use = dictionary_path
        else:
            path_to_use = Path("data/greek_dictionary.json")

        if path_to_use.exists():
            try:
                with open(path_to_use, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    words = set()
                    if isinstance(data, list):
                        words.update(word.lower() for word in data)
                        words.update(word.upper() for word in data)
                    elif isinstance(data, dict):
                        for key, value in data.items():
                            if isinstance(value, list):
                                words.update(word.lower() for word in value)
                                words.update(word.upper() for word in value)
                    logger.info(f"Loaded {len(words)} Greek words from dictionary.")
                    return words
            except Exception as e:
                logger.warning(f"Could not load Greek dictionary: {e}")

        logger.info("No dictionary found, using common words as fallback.")
        return self.common_greek_words

    def _initialize_gr_nlp_toolkit(self):
        """Initialize the gr-nlp-toolkit if available."""
        try:
            import gr_nlp_toolkit
        except ImportError:
            logger.warning(
                "gr-nlp-toolkit not available. Install with: pip install gr-nlp-toolkit"
            )
            self.gr_nlp_pipeline = None
            return
        try:
            # Use only POS tagging as it's lighter than full pipeline
            self.gr_nlp_pipeline = gr_nlp_toolkit.Pipeline("pos", use_cpu=True)
            logger.info("Initialized gr-nlp-toolkit successfully")
        except ImportError:
            logger.warning(
                "gr-nlp-toolkit not available. Install with: pip install gr-nlp-toolkit"
            )
            self.gr_nlp_pipeline = None
        except Exception as e:
            logger.warning(f"Failed to initialize gr-nlp-toolkit: {e}")
            self.gr_nlp_pipeline = None

    def _normalize_greek_text(self, text: str) -> str:
        """Normalize Greek text by removing accents and stress marks for better matching."""
        # Map accented characters to their non-accented equivalents
        accent_map = str.maketrans(
            {
                "ά": "α",
                "έ": "ε",
                "ή": "η",
                "ί": "ι",
                "ό": "ο",
                "ύ": "υ",
                "ώ": "ω",
                "Ά": "Α",
                "Έ": "Ε",
                "Ή": "Η",
                "Ί": "Ι",
                "Ό": "Ο",
                "Ύ": "Υ",
                "Ώ": "Ω",
                "ΐ": "ι",
                "ΰ": "υ",
                "ϊ": "ι",
                "ϋ": "υ",
                "Ϊ": "Ι",
                "Ϋ": "Υ",
            }
        )
        return text.translate(accent_map)

    def _extract_words(self, text: str) -> List[str]:
        """Extract words from text, filtering out numbers and very short tokens."""
        words = re.findall(r"[Α-ΩΆΈΉΊΌΎΏΪΫα-ωάέήίόύώϊϋΐΰ]+", text)
        return [word for word in words if len(word) >= 2]

    def _check_common_words_presence(
        self, text: str, verbose: bool = False
    ) -> Tuple[bool, float]:
        """Strategy 1: Check if sufficient common Greek words appear as whole words in the text.

        Uses coverage-based approach: checks what % of the text's words are recognizable Greek words.
        This is more robust than checking what % of our detection word list appears in the text.
        """
        start_time = time.time()

        # Normalize and convert text to lowercase for better matching
        text_normalized = self._normalize_greek_text(text.lower())

        # Extract actual words from text for comparison
        text_words = self._extract_words(text_normalized)
        text_words_set = set(text_words)
        text_word_count = len(text_words)

        if text_word_count == 0:
            return False, time.time() - start_time

        # Build normalized detection word sets by category
        detection_sets = {
            "common_words": {
                self._normalize_greek_text(w.lower()) for w in self.common_greek_words
            },
            "stopwords": set(),
            "administrative": set(),
        }

        # Normalize stopwords (multi-word stopwords broken into individual words)
        for stopword in self.greek_stopwords:
            words_in_stopword = self._normalize_greek_text(stopword.lower()).split()
            detection_sets["stopwords"].update(words_in_stopword)

        # Normalize administrative indicators
        for indicator in self.administrative_indicators:
            clean_indicator = self._normalize_greek_text(
                indicator.replace(".", "").lower()
            )
            if len(clean_indicator) >= 2:
                detection_sets["administrative"].add(clean_indicator)

        # Combine all detection words
        all_detection_words = set()
        for category_words in detection_sets.values():
            all_detection_words.update(category_words)

        # Track which text words match which categories
        matched_text_words = {
            "common_words": set(),
            "stopwords": set(),
            "administrative": set(),
            "unmatched": set(),
        }

        for text_word in text_words_set:
            matched = False
            if text_word in detection_sets["common_words"]:
                matched_text_words["common_words"].add(text_word)
                matched = True
            if text_word in detection_sets["stopwords"]:
                matched_text_words["stopwords"].add(text_word)
                matched = True
            if text_word in detection_sets["administrative"]:
                matched_text_words["administrative"].add(text_word)
                matched = True
            if not matched:
                matched_text_words["unmatched"].add(text_word)

        # Calculate unique matched words (a word might be in multiple categories)
        unique_matched_words = set()
        for category in ["common_words", "stopwords", "administrative"]:
            unique_matched_words.update(matched_text_words[category])

        matched_word_count = len(unique_matched_words)

        # PRIMARY METRIC: What % of text words are recognizable? (Coverage)
        word_coverage_ratio = (
            matched_word_count / text_word_count if text_word_count > 0 else 0
        )

        # SECONDARY METRIC: Minimum absolute count for very short texts
        # For very short texts (<10 words), require at least 2 matches to avoid false positives
        # For longer texts, coverage ratio is the primary and sufficient metric
        if text_word_count < 10:
            min_matches_required = 2
            has_min_matches = matched_word_count >= min_matches_required
            # For very short texts, use minimum matches check
            is_corrupted = not has_min_matches
        else:
            # For normal/long texts, use coverage ratio exclusively
            # If less than 10% of words are recognizable, it's corrupted
            min_matches_required = int(
                text_word_count * self.coverage_ratio_threshold
            )  # 10% of text
            has_min_matches = matched_word_count >= min_matches_required
            low_coverage = word_coverage_ratio < self.coverage_ratio_threshold
            is_corrupted = low_coverage

        processing_time = time.time() - start_time

        # Verbose logging
        if verbose:
            logger.debug("=== Word Detection Detailed Analysis ===")
            logger.debug(f"Total unique words in text: {text_word_count}")
            logger.debug(f"Matched (valid) words: {matched_word_count}")
            logger.debug(f"Unmatched words: {len(matched_text_words['unmatched'])}")
            logger.debug(
                f"Coverage ratio: {word_coverage_ratio:.3f} ({word_coverage_ratio*100:.1f}% of text words are valid)"
            )
            logger.debug(
                f"Coverage threshold: {self.coverage_ratio_threshold} ({self.coverage_ratio_threshold*100:.1f}%)"
            )
            logger.debug(
                f"Minimum matches required: {min_matches_required} (has {matched_word_count})"
            )

            for category in ["common_words", "stopwords", "administrative"]:
                words = matched_text_words[category]
                logger.debug(f"\n{category.upper()} ({len(words)} matched):")
                if words:
                    sample_words = sorted(list(words))[:20]
                    logger.debug(f"  Matched: {', '.join(sample_words)}")
                    if len(words) > 20:
                        logger.debug(f"  ... and {len(words) - 20} more")
                else:
                    logger.debug(f"  No matches in this category")

            # Show unmatched words
            if matched_text_words["unmatched"]:
                sample_unmatched = sorted(list(matched_text_words["unmatched"]))[:30]
                logger.debug(
                    f"\nUNMATCHED WORDS ({len(matched_text_words['unmatched'])} total):"
                )
                logger.debug(f"  {', '.join(sample_unmatched)}")
                if len(matched_text_words["unmatched"]) > 30:
                    logger.debug(
                        f"  ... and {len(matched_text_words['unmatched']) - 30} more"
                    )

        # Store detailed stats for debugging
        self.performance_stats["word_detection"] = {
            "matched_words": matched_word_count,
            "text_word_count": text_word_count,
            "unmatched_word_count": len(matched_text_words["unmatched"]),
            "word_coverage_ratio": word_coverage_ratio,
            "min_matches_required": min_matches_required,
            "has_min_matches": has_min_matches,
            "matched_by_category": {
                k: len(v) for k, v in matched_text_words.items() if k != "unmatched"
            },
            "is_short_text": text_word_count < 10,
            "corruption_reasons": {
                "low_coverage": (
                    word_coverage_ratio < self.coverage_ratio_threshold
                    if text_word_count >= 10
                    else False
                ),
                "insufficient_matches": (
                    not has_min_matches if text_word_count < 10 else False
                ),
            },
        }

        if is_corrupted:
            if text_word_count < 10:
                logger.warning(
                    f"Corruption detected (short text): insufficient matches ({matched_word_count} < {min_matches_required})"
                )
            else:
                logger.warning(
                    f"Corruption detected: low coverage ({word_coverage_ratio:.3f} < {self.coverage_ratio_threshold}) "
                    f"- only {matched_word_count}/{text_word_count} words matched"
                )
        else:
            logger.debug(
                f"Word detection passed. {matched_word_count}/{text_word_count} words matched "
                f"(coverage: {word_coverage_ratio:.3f}, {word_coverage_ratio*100:.1f}%)"
            )

        return is_corrupted, processing_time

    def _get_all_detection_words(self) -> Set[str]:
        """Get combined set of common words, domain stopwords, and administrative indicators for detection.

        Note: This method is now primarily used by other strategies. The common_words strategy
        tracks categories separately for better diagnostics.
        """
        detection_words = self.common_greek_words.copy()

        # Add domain stopwords (converted to lowercase for consistency)
        for stopword in self.greek_stopwords:
            words_in_stopword = stopword.lower().split()
            detection_words.update(words_in_stopword)

        # Add administrative indicators (normalized to lowercase)
        for indicator in self.administrative_indicators:
            # Strip dots and convert to lowercase for matching
            clean_indicator = indicator.replace(".", "").lower()
            if len(clean_indicator) >= 2:  # Only add if at least 2 chars
                detection_words.add(clean_indicator)

        return detection_words

    def _check_dictionary_ratio(self, words: List[str]) -> Tuple[bool, float]:
        """Strategy 2: Check ratio of words found in Greek dictionary."""
        start_time = time.time()

        if not self.greek_dictionary or len(words) < 10:
            logger.warning(
                "Greek dictionary not initialized or not enough words to check. Returning no corruption detected."
            )
            return False, time.time() - start_time

        # Sample words for performance (check first 50 words)
        sample_words = words[:50]

        # Check both lowercase and uppercase variants
        found_words = 0
        for word in sample_words:
            if (
                word.lower() in self.greek_dictionary
                or word.upper() in self.greek_dictionary
            ):
                found_words += 1

        # Calculate ratio of dictionary words
        dictionary_ratio = found_words / len(sample_words)
        processing_time = time.time() - start_time

        # If less than 20% of words are in dictionary, likely corrupted
        is_corrupted = dictionary_ratio < 0.2
        if is_corrupted:
            logger.warning(
                f"Corruption heuristic: Low dictionary ratio ({dictionary_ratio:.2f})."
            )

        return is_corrupted, processing_time

    def _check_gr_nlp_toolkit(self, text: str) -> Tuple[bool, float]:
        """Strategy 3: Use gr-nlp-toolkit for advanced analysis."""
        start_time = time.time()

        if not self.gr_nlp_pipeline:
            logger.warning(
                "gr-nlp-toolkit pipeline not initialized. Returning no corruption detected."
            )
            return False, time.time() - start_time

        try:
            # Take a sample of text to avoid heavy processing
            sample_text = text[:500]  # First 500 characters
            doc = self.gr_nlp_pipeline(sample_text)

            # Count tokens that got valid POS tags vs invalid/unknown
            valid_tokens = 0
            total_tokens = len(doc.tokens)

            if total_tokens == 0:
                return True, time.time() - start_time

            for token in doc.tokens:
                # If the toolkit can assign a valid POS tag, it's likely a real word
                if (
                    hasattr(token, "upos") and token.upos and token.upos != "X"
                ):  # 'X' is usually for unknown/foreign
                    valid_tokens += 1

            # If less than 30% of tokens get valid POS tags, likely corrupted
            valid_ratio = valid_tokens / total_tokens
            is_corrupted = valid_ratio < 0.3

            processing_time = time.time() - start_time

            if is_corrupted:
                logger.warning(
                    f"Corruption heuristic: Low valid POS ratio ({valid_ratio:.2f}) from gr-nlp-toolkit."
                )

            return is_corrupted, processing_time

        except Exception as e:
            logger.warning(f"Error in gr-nlp-toolkit analysis: {e}")
            return False, time.time() - start_time

    def _check_word_length_distribution(self, words: List[str]) -> bool:
        """Check for unusual word length patterns that suggest corruption."""
        if len(words) < 20:
            return False

        word_lengths = [len(word) for word in words]

        # Check for excessive very long words
        very_long_words = sum(1 for length in word_lengths if length > 15)
        if very_long_words / len(words) > 0.15:
            logger.warning("Corruption heuristic: Too many very long words.")
            return True

        # Check average length - Greek words typically average 6-8 characters
        avg_length = sum(word_lengths) / len(words)
        if avg_length > 12:
            logger.warning(
                f"Corruption heuristic: Unusual average word length: {avg_length:.1f}"
            )
            return True

        return False

    def _check_character_validity(
        self, text: str
    ) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Check for high percentage of non-Greek/non-standard characters.
        Returns:
            Tuple[bool, float, Dict]: (is_corrupted, ratio_invalid, debug_info)
        """
        lines = text.splitlines()
        sample_lines = lines[:10] + lines[-10:] if len(lines) > 20 else lines

        non_valid_chars = 0
        total_chars_sampled = 0
        invalid_chars_found = {}  # Track which invalid chars we find
        sample_invalid_positions = []  # Track some examples with context

        for line_idx, line in enumerate(sample_lines):
            clean_line = line.strip()
            if not clean_line:
                continue

            for char_idx, char in enumerate(clean_line):
                total_chars_sampled += 1
                if not self.valid_greek_char_pattern.match(char):
                    non_valid_chars += 1

                    # Track this invalid character
                    if char in invalid_chars_found:
                        invalid_chars_found[char] += 1
                    else:
                        invalid_chars_found[char] = 1

                    # Store some examples with context (first 10)
                    if len(sample_invalid_positions) < 10:
                        start_pos = max(0, char_idx - 5)
                        end_pos = min(len(clean_line), char_idx + 6)
                        context = clean_line[start_pos:end_pos]
                        sample_invalid_positions.append(
                            {
                                "char": char,
                                "char_code": ord(char),
                                "hex_code": hex(ord(char)),
                                "line_idx": line_idx,
                                "char_idx": char_idx,
                                "context": context,
                                "context_highlight": context[: char_idx - start_pos]
                                + f"[{char}]"
                                + context[char_idx - start_pos + 1 :],
                            }
                        )

        ratio_non_valid = (
            non_valid_chars / total_chars_sampled if total_chars_sampled > 0 else 0
        )
        is_corrupted = ratio_non_valid > 0.7

        debug_info = {
            "total_chars_sampled": total_chars_sampled,
            "non_valid_chars": non_valid_chars,
            "ratio_non_valid": ratio_non_valid,
            "invalid_chars_found": invalid_chars_found,
            "sample_invalid_positions": sample_invalid_positions,
            "lines_sampled": len(sample_lines),
            "total_lines": len(lines),
        }

        if is_corrupted:
            logger.warning(
                f"Corruption heuristic: High ratio of non-valid characters ({ratio_non_valid:.2f})."
            )
            logger.debug(f"Invalid characters found: {invalid_chars_found}")
            logger.debug(
                f"Sample invalid positions: {sample_invalid_positions[:3]}"
            )  # Log first 3 examples

        return is_corrupted, ratio_non_valid, debug_info

    def is_text_corrupted(self, text: str, min_length_for_check: int = 100) -> bool:
        """Detects if the text is likely corrupted using the selected strategy."""
        if not text or len(text) < min_length_for_check:
            return False

        total_start_time = time.time()

        # Heuristic 1: High percentage of non-Greek/non-standard characters
        char_corrupted, char_ratio, char_debug = self._check_character_validity(text)

        # Store character validation info in performance stats for debugging
        self.performance_stats["character_validation"] = {
            "ratio_invalid": char_ratio,
            "debug_info": char_debug,
        }

        if char_corrupted:
            return True

        # Apply strategy-specific heuristics, verbose=self.verbose
        if self.strategy == CorruptionDetectionStrategy.COMMON_WORDS:
            is_corrupted, strategy_time = self._check_common_words_presence(
                text, verbose=True
            )
            self.performance_stats["common_words"] = strategy_time

        elif self.strategy == CorruptionDetectionStrategy.GREEK_DICTIONARY:
            words = self._extract_words(text)
            is_corrupted, strategy_time = self._check_dictionary_ratio(words)
            self.performance_stats["dictionary"] = strategy_time

        elif self.strategy == CorruptionDetectionStrategy.GR_NLP_TOOLKIT:
            is_corrupted, strategy_time = self._check_gr_nlp_toolkit(text)
            self.performance_stats["gr_nlp_toolkit"] = strategy_time

        elif self.strategy == CorruptionDetectionStrategy.HYBRID:
            # Try common words first (fastest), verbose=self.verbose
            common_corrupted, common_time = self._check_common_words_presence(text)
            self.performance_stats["common_words"] = common_time

            if common_corrupted:
                # If common words suggest corruption, verify with dictionary
                words = self._extract_words(text)
                dict_corrupted, dict_time = self._check_dictionary_ratio(words)
                self.performance_stats["dictionary"] = dict_time
                is_corrupted = dict_corrupted
            else:
                is_corrupted = False
        else:
            is_corrupted = False

        # Additional check: word length distribution
        if not is_corrupted:
            words = self._extract_words(text)
            if self._check_word_length_distribution(words):
                is_corrupted = True

        total_time = time.time() - total_start_time
        self.performance_stats["total"] = total_time

        return is_corrupted

    def get_performance_stats(self) -> Dict[str, float]:
        """Get performance statistics for the last corruption check."""
        return self.performance_stats.copy()

    def benchmark_strategies(self, text: str) -> Dict[str, Dict[str, Any]]:
        """Benchmark all available strategies on the given text."""
        results = {}

        # Test Common Words strategy
        original_strategy = self.strategy

        try:
            self.strategy = CorruptionDetectionStrategy.COMMON_WORDS
            start_time = time.time()
            common_result = self.is_text_corrupted(text)
            common_time = time.time() - start_time
            results["common_words"] = {
                "is_corrupted": common_result,
                "time": common_time,
                "available": True,
            }
        except Exception as e:
            results["common_words"] = {"available": False, "error": str(e)}

        # Test Dictionary strategy
        if self.greek_dictionary:
            try:
                self.strategy = CorruptionDetectionStrategy.GREEK_DICTIONARY
                start_time = time.time()
                dict_result = self.is_text_corrupted(text)
                dict_time = time.time() - start_time
                results["dictionary"] = {
                    "is_corrupted": dict_result,
                    "time": dict_time,
                    "available": True,
                }
            except Exception as e:
                results["dictionary"] = {"available": False, "error": str(e)}
        else:
            results["dictionary"] = {
                "available": False,
                "error": "No dictionary loaded",
            }

        # Test GR-NLP-Toolkit strategy
        if self.gr_nlp_pipeline:
            try:
                self.strategy = CorruptionDetectionStrategy.GR_NLP_TOOLKIT
                start_time = time.time()
                nlp_result = self.is_text_corrupted(text)
                nlp_time = time.time() - start_time
                results["gr_nlp_toolkit"] = {
                    "is_corrupted": nlp_result,
                    "time": nlp_time,
                    "available": True,
                }
            except Exception as e:
                results["gr_nlp_toolkit"] = {"available": False, "error": str(e)}
        else:
            results["gr_nlp_toolkit"] = {
                "available": False,
                "error": "gr-nlp-toolkit not initialized",
            }

        # Restore original strategy
        self.strategy = original_strategy

        return results

    def remove_stopwords(self, text: str) -> str:
        """Removes predefined stopwords from the text."""
        processed_text = text
        for stopword in self.greek_stopwords:
            pattern = re.compile(
                r"\b" + re.escape(stopword) + r"\b", re.IGNORECASE | re.UNICODE
            )
            processed_text = pattern.sub("", processed_text)

        processed_text = re.sub(r"\s{2,}", " ", processed_text).strip()
        return processed_text

    def preprocess(self, text: str) -> Tuple[str, bool]:
        """
        Applies all preprocessing steps.
        Returns:
            Tuple[str, bool]: (processed_text, is_corrupted_flag)
        """
        if not text or text.isspace():
            return PreprocessingResult(
                processed_text="",
                is_corrupted=False,
                confidence_score=1.0,
                performance_stats={},
                corruption_indicators={},
            )

        self.performance_stats = {}

        # 0. Decode HTML entities (e.g., &lt; → <, &amp; → &)
        text = html.unescape(text)

        # 1. Detect corruption on the original raw text
        is_corrupted = self.is_text_corrupted(text)

        # 2. Calculate confidence score based on multiple factors
        confidence_score = self._calculate_confidence_score()

        # 3. Perform stopword removal and other cleaning
        processed_text = self.remove_stopwords(text)

        # 4. Gather corruption indicators for transparency
        corruption_indicators = self._gather_corruption_indicators()

        return PreprocessingResult(
            processed_text=processed_text,
            is_corrupted=is_corrupted,
            confidence_score=confidence_score,
            performance_stats=self.performance_stats.copy(),
            corruption_indicators=corruption_indicators,
        )

    def debug_character_validation(self, text: str) -> Dict[str, Any]:
        """
        Debug method to analyze character validation in detail.
        Use this to understand why text is being flagged as corrupted.
        """
        _, _, debug_info = self._check_character_validity(text)

        print("=== Character Validation Debug Report ===")
        print(f"Total characters sampled: {debug_info['total_chars_sampled']}")
        print(f"Invalid characters found: {debug_info['non_valid_chars']}")
        print(f"Invalid ratio: {debug_info['ratio_non_valid']:.3f}")
        print(
            f"Lines sampled: {debug_info['lines_sampled']} out of {debug_info['total_lines']}"
        )

        if debug_info["invalid_chars_found"]:
            print("\nInvalid characters breakdown:")
            for char, count in sorted(
                debug_info["invalid_chars_found"].items(),
                key=lambda x: x[1],
                reverse=True,
            ):
                print(f"  '{char}' (U+{ord(char):04X}): {count} times")

        if debug_info["sample_invalid_positions"]:
            print("\nSample invalid character positions:")
            for i, pos in enumerate(
                debug_info["sample_invalid_positions"][:5]
            ):  # Show first 5
                print(
                    f"  {i+1}. Character '{pos['char']}' (U+{pos['char_code']:04X}) at line {pos['line_idx']}, position {pos['char_idx']}"
                )
                print(f"     Context: {pos['context_highlight']}")

        print("\nValid character pattern:")
        print(f"  {self.valid_greek_char_pattern.pattern}")

        return debug_info

    def _calculate_confidence_score(self) -> float:
        """Calculate confidence score for corruption detection (0.0 = no confidence, 1.0 = very confident)."""
        confidence_factors = []

        # Factor 1: Word detection confidence
        if "word_detection" in self.performance_stats:
            word_stats = self.performance_stats["word_detection"]
            coverage_ratio = word_stats.get("word_coverage_ratio", 0)
            has_min_matches = word_stats.get("has_min_matches", False)

            # Higher coverage = higher confidence in "not corrupted"
            word_confidence = min(
                1.0, coverage_ratio * 3
            )  # Scale up since threshold is 0.10
            if has_min_matches:
                word_confidence = max(
                    word_confidence, 0.5
                )  # Boost if minimum matches met
            confidence_factors.append(word_confidence)

        # Factor 2: Character validity confidence
        if "character_validation" in self.performance_stats:
            char_stats = self.performance_stats["character_validation"]
            invalid_ratio = char_stats.get("ratio_invalid", 0)

            # Lower invalid ratio = higher confidence in "not corrupted"
            char_confidence = max(0.0, 1.0 - (invalid_ratio * 1.5))
            confidence_factors.append(char_confidence)

        # Factor 3: Strategy-specific confidence
        if (
            self.strategy == CorruptionDetectionStrategy.COMMON_WORDS
            and "common_words" in self.performance_stats
        ):
            # Fast execution suggests simple, reliable detection
            exec_time = self.performance_stats.get("common_words", 0)
            time_confidence = max(
                0.5, 1.0 - (exec_time * 10)
            )  # Penalty for slow execution
            confidence_factors.append(time_confidence)

        # Return average confidence, or 0.5 if no factors available
        return (
            sum(confidence_factors) / len(confidence_factors)
            if confidence_factors
            else 0.5
        )

    def _gather_corruption_indicators(self) -> Dict[str, Any]:
        """Gather detailed information about what triggered corruption detection."""
        indicators = {}

        # Word-based indicators
        if "word_detection" in self.performance_stats:
            word_stats = self.performance_stats["word_detection"]
            indicators["word_analysis"] = {
                "matched_words": word_stats.get("matched_words", 0),
                "text_word_count": word_stats.get("text_word_count", 0),
                "unmatched_word_count": word_stats.get("unmatched_word_count", 0),
                "coverage_ratio": word_stats.get("word_coverage_ratio", 0),
                "min_matches_required": word_stats.get("min_matches_required", 0),
                "has_min_matches": word_stats.get("has_min_matches", False),
                "matched_by_category": word_stats.get("matched_by_category", {}),
                "thresholds": {
                    "coverage_ratio_threshold": self.coverage_ratio_threshold
                },
            }

        # Character-based indicators
        if "character_validation" in self.performance_stats:
            char_stats = self.performance_stats["character_validation"]
            char_debug = char_stats.get("debug_info", {})
            indicators["character_analysis"] = {
                "invalid_ratio": char_debug.get("ratio_non_valid", 0),
                "invalid_char_count": char_debug.get("non_valid_chars", 0),
                "total_chars_sampled": char_debug.get("total_chars_sampled", 0),
                "threshold": char_debug.get(
                    "threshold_used", self.char_validity_threshold
                ),
                "top_invalid_chars": dict(
                    list(char_debug.get("invalid_chars_found", {}).items())[:5]
                ),  # Top 5 invalid chars
            }

        # Strategy used
        indicators["strategy_used"] = self.strategy.value

        return indicators
