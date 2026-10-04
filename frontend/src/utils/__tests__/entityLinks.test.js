import { buildEntityUrl } from '../entityLinks';

describe('buildEntityUrl', () => {
  test('carries the date window when both bounds are present', () => {
    expect(
      buildEntityUrl('afm', '802388731', {
        start_date: '2025-09-29',
        end_date: '2026-09-28',
      })
    ).toBe('/entity/afm/802388731?start_date=2025-09-29&end_date=2026-09-28');
  });

  test('works for organization entities', () => {
    expect(
      buildEntityUrl('organization', '900000001', {
        start_date: '2026-01-01',
        end_date: '2026-01-31',
      })
    ).toBe('/entity/organization/900000001?start_date=2026-01-01&end_date=2026-01-31');
  });

  test('returns a bare path when the date range is missing', () => {
    expect(buildEntityUrl('afm', '802388731', null)).toBe('/entity/afm/802388731');
    expect(buildEntityUrl('afm', '802388731', {})).toBe('/entity/afm/802388731');
  });

  test('returns a bare path when only one bound is present', () => {
    expect(
      buildEntityUrl('afm', '802388731', { start_date: '2025-09-29' })
    ).toBe('/entity/afm/802388731');
    expect(
      buildEntityUrl('afm', '802388731', { end_date: '2026-09-28' })
    ).toBe('/entity/afm/802388731');
  });

  test('adds direct_assignments_only when directOnly is set', () => {
    expect(
      buildEntityUrl(
        'afm',
        '802388731',
        { start_date: '2025-09-29', end_date: '2026-09-28' },
        { directOnly: true }
      )
    ).toBe(
      '/entity/afm/802388731?start_date=2025-09-29&end_date=2026-09-28&direct_assignments_only=true'
    );
  });

  test('can carry directOnly with no date range', () => {
    expect(
      buildEntityUrl('afm', '802388731', null, { directOnly: true })
    ).toBe('/entity/afm/802388731?direct_assignments_only=true');
  });

  test('omits direct_assignments_only by default', () => {
    expect(
      buildEntityUrl('afm', '802388731', {
        start_date: '2025-09-29',
        end_date: '2026-09-28',
      })
    ).not.toContain('direct_assignments_only');
  });
});
