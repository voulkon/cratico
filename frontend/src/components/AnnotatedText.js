import React, { useMemo } from 'react';
import './AnnotatedText.css';

/**
 * Render document text with highlighted spans from text processes.
 *
 * Props:
 *   rawText    — the full document text
 *   runs       — [{ process, method, version, status, spans: [...] }, ...]
 *   visible    — set of process slugs to overlay (default: all completed)
 *   onSpanClick(span, run) — optional click callback
 *
 * The splitter sorts all visible spans by start, resolves overlaps by a
 * fixed label priority, and emits <mark> nodes with CSS class
 * `text-span--{label}`.
 */

// Priority ordering: lower index = higher priority (wins when spans overlap).
// "chosen" variants within a label are rendered via the `value.chosen` flag,
// not as separate labels.
const LABEL_PRIORITY = [
  'amount',
  'date',
  'subject',
  'main_point',
  'signer',
  'entity',
  'boilerplate',
  'useless',
];

// Span labels → human-readable names (for the legend)
const LABEL_NAMES = {
  amount: 'Amount',
  date: 'Date',
  subject: 'Subject / Title',
  main_point: 'Main Point',
  signer: 'Signer',
  entity: 'Entity',
  boilerplate: 'Boilerplate',
  useless: 'Low-value region',
};

// Colors are defined in CSS — this just maps for the legend swatches
const LABEL_CLASSES = Object.keys(LABEL_NAMES).reduce((acc, l) => {
  acc[l] = `text-span--${l}`;
  return acc;
}, {});

/**
 * Build a flattened & deduped list of visible spans, resolving overlaps by
 * priority.  Each span gets a CSS modifier class derived from its value
 * (e.g. `text-span--amount-chosen`, `text-span--date`).
 */
function resolveSpans(runs, visibleSet) {
  const activeRuns = runs.filter(
    r => r.status === 'COMPLETED' && (!visibleSet || visibleSet.has(r.process))
  );
  const flat = [];
  for (const run of activeRuns) {
    for (const span of run.spans || []) {
      flat.push({ ...span, _process: run.process });
    }
  }
  flat.sort((a, b) => a.start - b.start || a.end - b.end);

  // Greedy resolve overlaps: when two spans overlap, the one with higher
  // label priority wins.  Non-overlapping spans coexist.
  const resolved = [];
  for (const span of flat) {
    // Check overlap with the last resolved span
    const prev = resolved[resolved.length - 1];
    if (prev && span.start < prev.end) {
      const priA = LABEL_PRIORITY.indexOf(span.label);
      const priB = LABEL_PRIORITY.indexOf(prev.label);
      if (priA < priB) {
        // Current span wins — replace last
        resolved[resolved.length - 1] = span;
      }
      // else skip current span (prev wins)
    } else {
      resolved.push(span);
    }
  }
  return resolved;
}

function spanClassName(span) {
  const base = LABEL_CLASSES[span.label] || 'text-span--unknown';
  if (span.value?.chosen) return `${base} text-span--chosen`;
  if (span.value?.clone_of) return `${base} text-span--clone`;
  return base;
}

export default function AnnotatedText({ rawText, runs, visible, onSpanClick }) {
  const visibleSet = useMemo(() => (visible ? new Set(visible) : null), [visible]);
  const resolved = useMemo(() => resolveSpans(runs, visibleSet), [runs, visibleSet]);

  // Determine which labels appear in the resolved spans (for the legend)
  const usedLabels = useMemo(() => {
    const set = new Set();
    for (const s of resolved) set.add(s.label);
    return [...set];
  }, [resolved]);

  // Build the interleaved text + marks
  const nodes = [];
  let cursor = 0;
  for (let i = 0; i < resolved.length; i++) {
    const span = resolved[i];
    if (span.start > cursor) {
      nodes.push(
        <span key={`g-${i}`}>{rawText.slice(cursor, span.start)}</span>
      );
    }
    nodes.push(
      <mark
        key={`s-${i}`}
        className={spanClassName(span)}
        title={JSON.stringify(span.value, null, 2)}
        onClick={onSpanClick ? () => onSpanClick(span, span._process) : undefined}
      >
        {rawText.slice(span.start, span.end)}
      </mark>
    );
    cursor = span.end;
  }
  if (cursor < rawText.length) {
    nodes.push(
      <span key={`g-end`}>{rawText.slice(cursor)}</span>
    );
  }

  return (
    <div className="annotated-text">
      <Legend labels={usedLabels} />
      <pre className="annotated-text-content">{nodes}</pre>
    </div>
  );
}

function Legend({ labels }) {
  if (!labels.length) return null;
  return (
    <div className="text-span-legend">
      {labels.map(l => (
        <span key={l} className="legend-item">
          <span className={`legend-swatch ${LABEL_CLASSES[l] || ''}`} />
          {LABEL_NAMES[l] || l}
        </span>
      ))}
    </div>
  );
}

export { LABEL_NAMES, LABEL_CLASSES };
