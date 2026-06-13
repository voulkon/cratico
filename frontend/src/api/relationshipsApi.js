import apiClient from './client';

/**
 * API methods for entity and counterpart relationships
 */
const relationshipsApi = {
  /**
   * Get top organizations for a specific AFM entity
   * @param {string} afm - The AFM of the entity
   * @param {Object} params - Query parameters (start_date, end_date, limit, offset)
   */
  getTopOrganizations: async (afm, params = {}) => {
    const queryParams = new URLSearchParams();

    if (params.start_date) queryParams.set('start_date', params.start_date);
    if (params.end_date) queryParams.set('end_date', params.end_date);
    if (params.limit) queryParams.set('limit', params.limit.toString());
    if (params.offset) queryParams.set('offset', params.offset.toString());

    const response = await apiClient.get(`/entities/${afm}/top-organizations/?${queryParams}`);
    return response.data;
  },

  /**
   * Get top counterparts (entities) for a specific organization
   * @param {string} orgUid - The UID of the organization
   * @param {Object} params - Query parameters (start_date, end_date, limit, offset)
   */
  getTopCounterparts: async (orgUid, params = {}) => {
    const queryParams = new URLSearchParams();

    if (params.start_date) queryParams.set('start_date', params.start_date);
    if (params.end_date) queryParams.set('end_date', params.end_date);
    if (params.limit) queryParams.set('limit', params.limit.toString());
    if (params.offset) queryParams.set('offset', params.offset.toString());
    if (params.search) queryParams.set('q', params.search);

    const response = await apiClient.get(`/organizations/${orgUid}/top-counterparts/?${queryParams}`);
    return response.data;
  },

  /**
   * Get relationship details and decisions between a specific entity and organization
   * @param {string} afm - The AFM of the entity
   * @param {string} orgUid - The UID of the organization
   * @param {Object} params - Query parameters (start_date, end_date, page, page_size, sort_by, etc.)
   */
  getRelationshipDecisions: async (afm, orgUid, params = {}) => {
    const queryParams = new URLSearchParams({
      entity_afm: afm,
      organization_uid: orgUid,
      ...params
    });

    // Remove undefined/null values
    for (const [key, value] of queryParams.entries()) {
      if (value === 'undefined' || value === 'null' || value === '') {
        queryParams.delete(key);
      }
    }

    const response = await apiClient.get(`/explore/decisions-optimized/?${queryParams}`);
    return response.data;
  }
};

export default relationshipsApi;
