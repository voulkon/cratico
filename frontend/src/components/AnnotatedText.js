import React, { useMemo } from 'react';
import './AnnotatedText.css';

/**
 * Render document text with highlighted spans from text processes.
 *
 * Props:
 *   rawText         — the full document text
 *   runs            — [{ process, method, version, status, spans: [...] }, ...]
 *   activeProcesses — Set of process slugs to overlay
 *   processList     — [{ slug, name, description, color, methods }, ...]
 *                       colors come from the backend — no hardcoding
 *   onSpanClick(region) — optional click callback
 *
 * Uses character-level process tracking so overlapping spans from
 * different processes coexist.  Multi-process overlap regions get a
 * special combined style.
 */

// ── helpers ──────────────────────────────────────────────────────────

/** "ff9800" | "#FF9800" → "rgba(255, 152, 0, α)" */
function hexToRgba(hex, alpha) {
  hex = hex.replace(/^#/, '');
  if (hex.length === 3) hex = hex[0]+hex[0]+hex[1]+hex[1]+hex[2]+hex[2];
  const r = parseInt(hex.substring(0, 2), 16);
  const g = parseInt(hex.substring(2, 4), 16);
  const b = parseInt(hex.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function getColor(slug, processMap) {
  return processMap[slug]?.color || '#757575';
}

/**
 * Build a character-level map: for each index in rawText, which process
 * slugs have a span covering that position (only active, completed runs).
 */
function buildCharProcessMap(rawText, runs, activeProcesses) {
  const len = rawText.length;
  const map = new Array(len);
  for (let i = 0; i < len; i++) map[i] = new Set();

  for (const run of runs) {
    if (run.status !== 'COMPLETED') continue;
    if (!activeProcesses.has(run.process)) continue;
    for (const span of run.spans || []) {
      const from = Math.max(0, span.start);
      const to = Math.min(len, span.end);
      for (let i = from; i < to; i++) map[i].add(run.process);
    }
  }
  return map;
}

function charMapToRegions(charMap) {
  const regions = [];
  let i = 0;
  const len = charMap.length;
  while (i < len) {
    const procs = charMap[i];
    let j = i + 1;
    while (j < len && setsEqual(charMap[j], procs)) j++;
    if (procs.size > 0) {
      regions.push({ from: i, to: j, processes: new Set(procs) });
    }
    i = j;
  }
  return regions;
}

function setsEqual(a, b) {
  if (a.size !== b.size) return false;
  for (const x of a) if (!b.has(x)) return false;
  return true;
}

// ── component ────────────────────────────────────────────────────────

export default function AnnotatedText({ rawText, runs, activeProcesses, processList, onSpanClick }) {
  const activeSet = useMemo(
    () => (activeProcesses ? new Set(activeProcesses) : new Set()),
    [activeProcesses]
  );

  // slug → { name, description, color }
  const processMap = useMemo(() => {
    const m = {};
    for (const p of processList || []) m[p.slug] = p;
    return m;
  }, [processList]);

  const regions = useMemo(() => {
    const charMap = buildCharProcessMap(rawText, runs, activeSet);
    return charMapToRegions(charMap);
  }, [rawText, runs, activeSet]);

  // Determine which slugs appear (for the legend)
  const activeSlugs = useMemo(() => {
    const set = new Set();
    for (const r of regions) for (const s of r.processes) set.add(s);
    return [...set].sort();
  }, [regions]);

  // Build interleaved text + marks
  const nodes = [];
  let cursor = 0;
  for (let i = 0; i < regions.length; i++) {
    const r = regions[i];
    if (r.from > cursor) {
      nodes.push(
        <span key={`g-${i}`}>{rawText.slice(cursor, r.from)}</span>
      );
    }

    const slugs = [...r.processes].sort();
    const tooltipLines = slugs.map(s => {
      const info = processMap[s];
      if (info?.description) return `${info.name}: ${info.description}`;
      return info?.name || s;
    });

    // Build dynamic style based on how many processes matched
    let style = {};
    if (slugs.length === 1) {
      const c = getColor(slugs[0], processMap);
      style = {
        backgroundColor: hexToRgba(c, 0.25),
        borderBottom: `2px solid ${hexToRgba(c, 0.90)}`,
      };
    } else if (slugs.length === 2) {
      const c1 = getColor(slugs[0], processMap);
      const c2 = getColor(slugs[1], processMap);
      style = {
        background: `repeating-linear-gradient(-45deg, ${hexToRgba(c1, 0.18)} 0px, ${hexToRgba(c1, 0.18)} 4px, ${hexToRgba(c2, 0.15)} 4px, ${hexToRgba(c2, 0.15)} 8px)`,
        borderBottom: `2px solid ${hexToRgba(c1, 0.85)}`,
        boxShadow: `0 3px 0 -1px ${hexToRgba(c2, 0.85)}`,
        paddingBottom: 2,
      };
    } else {
      // 3+ — hatched neutral
      style = {
        background: `repeating-linear-gradient(-45deg, rgba(180,180,180,0.20) 0px, rgba(180,180,180,0.20) 4px, rgba(180,180,180,0.10) 4px, rgba(180,180,180,0.10) 8px)`,
        border: '1px dashed rgba(180,180,180,0.6)',
      };
    }

    nodes.push(
      <mark
        key={`s-${i}`}
        className={slugs.length > 1 ? 'annot-mark annot-mark--multi' : 'annot-mark'}
        style={style}
        title={tooltipLines.join('\n\n')}
        onClick={onSpanClick ? () => onSpanClick(r) : undefined}
      >
        {rawText.slice(r.from, r.to)}
      </mark>
    );
    cursor = r.to;
  }
  if (cursor < rawText.length) {
    nodes.push(
      <span key="g-end">{rawText.slice(cursor)}</span>
    );
  }

  return (
    <div className="annotated-text">
      <Legend slugs={activeSlugs} processMap={processMap} />
      <pre className="annotated-text-content">{nodes}</pre>
    </div>
  );
}

function Legend({ slugs, processMap }) {
  if (!slugs.length) return null;
  return (
    <div className="text-span-legend">
      {slugs.map(slug => {
        const c = getColor(slug, processMap);
        return (
          <span key={slug} className="legend-item" title={processMap[slug]?.description || ''}>
            <span
              className="legend-swatch"
              style={{ backgroundColor: hexToRgba(c, 0.90) }}
            />
            {processMap[slug]?.name || slug}
          </span>
        );
      })}
    </div>
  );
}
