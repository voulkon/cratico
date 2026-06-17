import axios from 'axios';

/**
 * Public API client – no authentication headers attached.
 * Used for publicly shared bookmark/folder endpoints.
 */
const publicApiClient = axios.create({
  baseURL: process.env.REACT_APP_API_URL || '/api',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

export default publicApiClient;
