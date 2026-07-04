import axios from 'axios';

// Create a global token getter that will be set by the app
let getAuthToken = null;
let isClerkAuth = false;

export const setTokenGetter = (getter, clerkMode = false) => {
  getAuthToken = getter;
  isClerkAuth = clerkMode;
};

const apiClient = axios.create({
  baseURL: process.env.REACT_APP_API_URL || '/api',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json'
  }
});

// Add interceptors for auth, etc.
apiClient.interceptors.request.use(async config => {
  // Get auth token if available
  if (getAuthToken) {
    try {
      const token = await getAuthToken();
      if (token) {
        // Use Bearer for Clerk JWT, Token for Django token auth
        config.headers.Authorization = isClerkAuth ? `Bearer ${token}` : `Token ${token}`;
      }
    } catch (error) {
      console.error('Error getting auth token:', error);
    }
  }
  return config;
},
  (error) => Promise.reject(error)
);

// Add response interceptor to handle rate limiting and defer-on-miss (202)
apiClient.interceptors.response.use(
  async (response) => {
    // ── Handle defer_on_miss: 202 Accepted → wait and retry ────────
    if (response.status === 202 && response.data?.status === 'warming') {
      const config = response.config;

      // Track retry count on the request config
      config.__deferRetryCount = config.__deferRetryCount || 0;
      const MAX_DEFER_RETRIES = 5;

      if (config.__deferRetryCount >= MAX_DEFER_RETRIES) {
        return Promise.reject(
          new Error('Data is taking too long to prepare. Please refresh the page.')
        );
      }
      config.__deferRetryCount++;

      const retryAfter = parseInt(response.headers['retry-after'], 10)
        || response.data?.retry_after
        || 30;

      console.log(
        `[Defer] Data warming in progress (attempt ${config.__deferRetryCount}/${MAX_DEFER_RETRIES}), `
        + `retrying in ${retryAfter}s...`
      );

      await new Promise(resolve => setTimeout(resolve, retryAfter * 1000));
      return apiClient.request(config);
    }

    // Store rate limit info for display
    if (response.headers['x-ratelimit-limit']) {
      const rateLimitInfo = {
        limit: parseInt(response.headers['x-ratelimit-limit']),
        remaining: parseInt(response.headers['x-ratelimit-remaining']),
        reset: parseInt(response.headers['x-ratelimit-reset'])
      };

      // Store in localStorage or context for UI display
      localStorage.setItem('rateLimitInfo', JSON.stringify(rateLimitInfo));

      // Dispatch event for components to listen to
      window.dispatchEvent(new CustomEvent('rateLimitUpdate', { detail: rateLimitInfo }));
    }

    return response;
  },
  (error) => {
    if (error.response?.status === 429) {
      // Rate limit exceeded
      const resetTime = error.response.headers['x-ratelimit-reset'];
      const resetDate = new Date(resetTime * 1000);

      // Create enhanced error with rate limit info
      const rateLimitError = new Error('Rate limit exceeded');
      rateLimitError.isRateLimit = true;
      rateLimitError.resetTime = resetDate;
      rateLimitError.message = error.response.data.error || error.response.data || 'Rate limit exceeded';

      // Dispatch event for global handling
      window.dispatchEvent(new CustomEvent('rateLimitExceeded', {
        detail: {
          resetTime: resetDate,
          message: rateLimitError.message
        }
      }));

      return Promise.reject(rateLimitError);
    }

    if (error.response?.status === 401) {
      // Unauthorized - user needs to sign in
      // Dispatch event for global handling
      window.dispatchEvent(new CustomEvent('authRequired', {
        detail: {
          message: 'Please sign in to access this feature'
        }
      }));

      return Promise.reject(error);
    }

    return Promise.reject(error);
  }
);

export default apiClient;
