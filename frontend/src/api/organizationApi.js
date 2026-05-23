import apiClient from './client';

const organizationApi = {
  getOrganizations: async () => {
    try {
      const response = await apiClient.get('/organizations/');
      return response.data;  // Extract data directly for convenience
    } catch (error) {
      console.error('Failed to fetch organizations:', error);
      throw error;  // Re-throw so calling code can handle it
    }
  },

  getOrgChart: async (orgId) => {
    try {
      const response = await apiClient.get(`/org-chart-api-dev/?org_uid=${orgId}`);
      return response.data;  // Extract data directly for convenience
    } catch (error) {
      console.error(`Failed to fetch org chart for ${orgId}:`, error);
      throw error;  // Re-throw so calling code can handle it
    }
  },

  searchOrganizations: async (query) => {
    try {
      // Use the universal search endpoint that returns the structure you expect
      const response = await apiClient.get(`/search-dev/?q=${encodeURIComponent(query)}&types=organization,signer&limit=10`);
      return response.data;
    } catch (error) {
      console.error('Failed to search organizations:', error);
      throw error;
    }
  }
};

export default organizationApi;
