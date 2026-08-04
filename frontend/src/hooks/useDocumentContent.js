import { useCallback } from 'react';
import apiClient from '../api/client';

const useDocumentContent = () => {
  const fetchContent = useCallback(async (decisionId) => {
    try {
      const response = await apiClient.get(`/decisions/${decisionId}/content/`);
      return response.data;
    } catch (error) {
      if (error.response) {
        const errorMessage =
          error.response.data?.error ||
          error.response.data?.message ||
          `HTTP ${error.response.status}: ${error.response.statusText}`;
        throw new Error(errorMessage);
      } else if (error.request) {
        throw new Error('No response from server');
      } else {
        throw new Error(error.message || 'Request failed');
      }
    }
  }, []);

  return { fetchContent };
};

export default useDocumentContent;
