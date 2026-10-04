/**
 * Cross-page link helpers that keep the date window intact.
 *
 * Why this exists
 * ───────────────
 * Dashboard cards rank entities over a specific period (e.g. the homepage's
 * "Year" selector).  If the link omits that window, ``EntityDetailPage``
 * falls back to its own progressive default range (walk back from the newest
 * month until ~5 decisions accumulate, hard-capped at 12 months), so the
 * landing page can show a completely different — much smaller — set of
 * decisions than the card summarised.  Seen in practice: a card reporting
 * "10 assignments / €366K" opened an entity page showing a single €1K
 * decision, purely because the two pages picked different windows.
 *
 * Carrying ``start_date``/``end_date`` in the URL makes the two agree, and
 * ``EntityDetailPage`` seeds its range slider from those params on load.
 *
 * Sections that are themselves restricted to direct assignments (e.g. the
 * banded €30k–€38k leaderboards) also pass ``directOnly`` so the landing page's
 * toolbar checkbox is pre-ticked and its decision list matches the card.
 */

/**
 * Build an entity-detail URL carrying the date window it was computed over.
 *
 * @param {string} entityType  'afm' | 'organization' | 'signer' | 'unit'
 * @param {string|number} entityId
 * @param {{start_date?: string, end_date?: string}|null} dateRange
 * @param {{directOnly?: boolean}} [options]
 * @returns {string} e.g. `/entity/afm/802388731?start_date=2025-09-29&end_date=2026-09-29`
 *                   or a bare path when there is nothing to carry.
 */
export const buildEntityUrl = (
  entityType,
  entityId,
  dateRange,
  { directOnly = false } = {}
) => {
  const base = `/entity/${entityType}/${entityId}`;

  const params = new URLSearchParams();

  const start = dateRange?.start_date;
  const end = dateRange?.end_date;
  if (start && end) {
    params.set('start_date', start);
    params.set('end_date', end);
  }

  if (directOnly) params.set('direct_assignments_only', 'true');

  const query = params.toString();
  return query ? `${base}?${query}` : base;
};

export default buildEntityUrl;
