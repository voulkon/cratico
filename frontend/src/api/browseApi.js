import apiClient from './client';

/**
 * Browse API service for alphabetical entity browsing.
 */

/**
 * Fetch a page of browse entities.
 *
 * @param {Object} params
 * @param {string}  params.type    - Entity type: 'all', 'organization', 'unit', 'signer',
 *                                    'company', 'companyperson', 'afmentity'
 * @param {string}  [params.letter] - First-letter filter (Greek or Latin, case-insensitive)
 * @param {string}  [params.q]      - Free-text prefix filter (case-insensitive)
 * @param {string}  [params.sort]   - 'asc' (default) or 'desc'
 * @param {number}  [params.offset] - Pagination offset (0-based)
 * @param {number}  [params.limit]  - Page size (max 200, default 50)
 * @returns {Promise<Object>} { results, has_more, total_count, available_letters }
 */
export const fetchBrowseEntities = async (params = {}) => {
  const response = await apiClient.get('/browse/entities/', { params });
  return response.data;
};
