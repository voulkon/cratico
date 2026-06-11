import apiClient from './client';

/**
 * Notification system API functions
 *
 * This module provides functions for managing notification subscriptions
 * and notifications in the user's account.
 */

// ============ API BASE PATHS ============
const NOTIFICATIONS_BASE = '/notifications';
const SUBSCRIPTIONS_BASE = `${NOTIFICATIONS_BASE}/subscriptions`;
const BATCHES_BASE = `${NOTIFICATIONS_BASE}/batches`;
const METADATA_BASE = '/notifications-meta/metadata';

// ============ SUBSCRIPTIONS ============

/**
 * Get all notification subscriptions for the current user
 * @returns {Promise<Array>} Array of subscription objects
 */
export async function getSubscriptions() {
  const response = await apiClient.get(`${SUBSCRIPTIONS_BASE}/`);
  return response.data;
}

/**
 * Get a specific subscription by ID
 * @param {number} id - Subscription ID
 * @returns {Promise<Object>} Subscription object
 */
export async function getSubscription(id) {
  const response = await apiClient.get(`${SUBSCRIPTIONS_BASE}/${id}/`);
  return response.data;
}

/**
 * Create a new notification subscription
 * Note: subscription_type is determined by backend based on which fields are provided
 * @param {Object} data - Subscription data
 * @param {string} [data.organization_uid] - Organization UID (for organization subscriptions)
 * @param {string} [data.entity_afm] - Entity AFM (for entity subscriptions)
 * @param {string} [data.relationship_org_uid] - Organization UID (for relationship subscriptions)
 * @param {string} [data.relationship_entity_afm] - Entity AFM (for relationship subscriptions)
 * @param {string} [data.person_name] - Person name (for person subscriptions)
 * @param {string} [data.signer_name] - Signer name (for signer subscriptions)
 * @param {Array<string>} [data.keywords] - Keywords to filter by
 * @param {number} [data.amount_min] - Minimum amount
 * @param {number} [data.amount_max] - Maximum amount
 * @param {Array<string>} [data.decision_types] - Decision type UIDs to filter by
 * @returns {Promise<Object>} Created subscription object
 */
export async function createSubscription(data) {
  const response = await apiClient.post(`${SUBSCRIPTIONS_BASE}/`, data);
  return response.data;
}

/**
 * Update an existing subscription
 * @param {number} id - Subscription ID
 * @param {Object} data - Fields to update
 * @returns {Promise<Object>} Updated subscription object
 */
export async function updateSubscription(id, data) {
  const response = await apiClient.patch(`${SUBSCRIPTIONS_BASE}/${id}/`, data);
  return response.data;
}

/**
 * Delete a subscription
 * @param {number} id - Subscription ID
 * @returns {Promise<void>}
 */
export async function deleteSubscription(id) {
  await apiClient.delete(`${SUBSCRIPTIONS_BASE}/${id}/`);
}

/**
 * Check if user is subscribed to an organization
 * @param {string} organizationUid - Organization UID
 * @returns {Promise<Object>} Object with { subscribed: boolean, subscription: Object|null }
 */
export async function checkOrganizationSubscription(organizationUid) {
  const response = await apiClient.get(`${SUBSCRIPTIONS_BASE}/check-organization/${organizationUid}/`);
  return response.data;
}

/**
 * Check if user is subscribed to an entity
 * @param {string} afm - Entity AFM
 * @returns {Promise<Object>} Object with { subscribed: boolean, subscription: Object|null }
 */
export async function checkEntitySubscription(afm) {
  const response = await apiClient.get(`${SUBSCRIPTIONS_BASE}/check-entity/${afm}/`);
  return response.data;
}

/**
 * Check if user is subscribed to a relationship
 * @param {string} organizationUid - Organization UID
 * @param {string} afm - Entity AFM
 * @returns {Promise<Object>} Object with { subscribed: boolean, subscription: Object|null }
 */
export async function checkRelationshipSubscription(organizationUid, afm) {
  const response = await apiClient.get(`${SUBSCRIPTIONS_BASE}/check-relationship/`, {
    params: { org_uid: organizationUid, entity_afm: afm }
  });
  return response.data;
}

/**
 * Check if user is subscribed to a signer
 * @param {string} name - Signer name
 * @returns {Promise<Object>} Object with { subscribed: boolean, subscription: Object|null }
 */
export async function checkSignerSubscription(name) {
  const encodedName = encodeURIComponent(name);
  const response = await apiClient.get(`${SUBSCRIPTIONS_BASE}/check-signer/${encodedName}/`);
  return response.data;
}

/**
 * Trigger an immediate check for a subscription
 * @param {number} id - Subscription ID
 * @param {number|null} [lookbackDays] - Optional: Number of days to look back.
 *                                       Defaults to 1 (yesterday's data) if not provided.
 * @returns {Promise<Object>} Object with results of the check including check_window_start and check_window_end
 */
export async function triggerCheckNow(id, lookbackDays = null) {
  const queryParams = lookbackDays ? { lookback_days: lookbackDays } : {};
  const response = await apiClient.post(
    `${SUBSCRIPTIONS_BASE}/${id}/check-now/`,
    null,
    { params: queryParams }
  );
  return response.data;
}

// ============ NOTIFICATION BATCHES ============

/**
 * Get all notification batches for the current user
 * @param {Object} [filters] - Filter options
 * @param {boolean} [filters.is_read] - Filter by read status
 * @param {boolean} [filters.is_dismissed] - Filter by dismissed status
 * @param {number} [filters.subscription_id] - Filter by subscription ID
 * @returns {Promise<Array>} Array of notification batch objects
 */
export async function getNotificationBatches(filters = {}) {
  const response = await apiClient.get(`${BATCHES_BASE}/`, { params: filters });
  return response.data;
}

/**
 * Get a specific notification batch by ID
 * @param {number} id - Batch ID
 * @returns {Promise<Object>} Batch object with details
 */
export async function getNotificationBatch(id) {
  const response = await apiClient.get(`${BATCHES_BASE}/${id}/`);
  return response.data;
}

/**
 * Get decisions within a notification batch (paginated)
 * @param {number} batchId - Batch ID
 * @param {number} [page=1] - Page number
 * @param {number} [pageSize=20] - Items per page
 * @param {boolean} [isViewed] - Filter by viewed status
 * @param {string} [sortBy='recent'] - Sort order (recent, oldest, amount_desc, amount_asc)
 * @returns {Promise<Object>} Paginated response with decisions
 */
export async function getBatchDecisions(batchId, page = 1, pageSize = 20, isViewed = null, sortBy = 'recent') {
  const params = { page, page_size: pageSize };
  if (isViewed !== null) {
    params.is_viewed = isViewed;
  }
  if (sortBy) {
    params.sort = sortBy;
  }
  const response = await apiClient.get(`${BATCHES_BASE}/${batchId}/decisions/`, { params });
  return response.data;
}

/**
 * Get all decisions from a subscription across all batches
 * @param {number} subscriptionId - Subscription ID
 * @param {number} [page=1] - Page number
 * @param {number} [pageSize=20] - Items per page
 * @param {boolean|null} [isViewed] - Filter by viewed status
 * @param {string} [sortBy='recent'] - Sort order (recent, oldest, amount_desc, amount_asc)
 * @returns {Promise<Object>} Paginated response with decisions and metadata
 */
export async function getSubscriptionAllDecisions(
  subscriptionId,
  page = 1,
  pageSize = 20,
  isViewed = null,
  sortBy = 'recent'
) {
  const params = new URLSearchParams({
    page: page.toString(),
    page_size: pageSize.toString(),
    sort: sortBy
  });

  if (isViewed !== null) {
    params.append('is_viewed', isViewed.toString());
  }

  const response = await apiClient.get(
    `${SUBSCRIPTIONS_BASE}/${subscriptionId}/all-decisions/?${params}`
  );
  return response.data;
}

/**
 * Mark a notification batch as read
 * @param {number} id - Batch ID
 * @returns {Promise<Object>} Response with status
 */
export async function markBatchRead(id) {
  const response = await apiClient.post(`${BATCHES_BASE}/${id}/mark-read/`);
  return response.data;
}

/**
 * Dismiss a notification batch
 * @param {number} id - Batch ID
 * @returns {Promise<Object>} Response with status
 */
export async function dismissBatch(id) {
  const response = await apiClient.post(`${BATCHES_BASE}/${id}/dismiss/`);
  return response.data;
}

/**
 * Get count of unread notification batches
 * @returns {Promise<Object>} Object with { unread_count: number }
 */
export async function getUnreadCount() {
  const response = await apiClient.get(`${BATCHES_BASE}/unread-count/`);
  return response.data;
}

/**
 * Mark all notification batches as read
 * @returns {Promise<Object>} Object with { marked_read: number }
 */
export async function markAllNotificationsRead() {
  // Get all unread batches
  const batches = await getNotificationBatches({ is_read: false });

  // Mark each as read
  const promises = batches.map(batch => markBatchRead(batch.id));
  await Promise.all(promises);

  return { marked_read: batches.length };
}

/**
 * Dismiss all notification batches
 * @returns {Promise<Object>} Object with { dismissed: number }
 */
export async function dismissAllNotifications() {
  // Get all non-dismissed batches
  const batches = await getNotificationBatches({ is_dismissed: false });

  // Dismiss each
  const promises = batches.map(batch => dismissBatch(batch.id));
  await Promise.all(promises);

  return { dismissed: batches.length };
}

// ============ METADATA ============

/**
 * Get system metadata (subscription types, filter options, etc.)
 * @returns {Promise<Object>} System metadata object
 */
export async function getSystemMetadata() {
  const response = await apiClient.get(`${METADATA_BASE}/`);
  return response.data;
}

/**
 * Get decision types
 * @param {Object} [params] - Query parameters
 * @param {boolean} [params.allowed_in_decisions] - Filter by allowed in decisions
 * @param {boolean} [params.has_children] - Filter by has children
 * @param {string} [params.parent_uid] - Filter by parent UID
 * @param {number} [params.limit] - Limit results
 * @returns {Promise<Object>} Object with { results: Array, count: number }
 */
export async function getDecisionTypes(params = {}) {
  const response = await apiClient.get(`${METADATA_BASE}/decision-types/`, { params });
  return response.data;
}

/**
 * Get popular decision types
 * @param {number} [limit=20] - Number of results
 * @returns {Promise<Object>} Object with { results: Array }
 */
export async function getPopularDecisionTypes(limit = 20) {
  const response = await apiClient.get(`${METADATA_BASE}/popular-decision-types/`, { params: { limit } });
  return response.data;
}

// ============ SEARCH ============

/**
 * Search for entities (organizations, signers, companies, persons)
 * @param {string} query - Search query
 * @param {Object} [options] - Search options
 * @param {Array<string>} [options.types] - Entity types to search for
 * @param {number} [options.limit] - Limit results per type
 * @returns {Promise<Object>} Object with results grouped by type
 */
export async function searchEntities(query, options = {}) {
  const params = {
    q: query,
    ...(options.types && { types: options.types.join(',') }),
    ...(options.limit && { limit: options.limit })
  };

  const response = await apiClient.get('/search/entities-fast', { params });
  return response.data;
}

// ============ HELPER FUNCTIONS ============

/**
 * Check if a subscription with given parameters already exists
 * Helper function to prevent duplicate subscriptions
 *
 * @param {Object} subscriptionData - Subscription parameters to check
 * @returns {Promise<Object|null>} Existing subscription or null
 */
export async function findExistingSubscription(subscriptionData) {
  const subscriptions = await getSubscriptions();

  return subscriptions.find(sub => {
    // Determine type from fields present in subscriptionData
    if (subscriptionData.organization_uid) {
      return sub.subscription_type === 'organization' &&
             sub.organization === subscriptionData.organization_uid;
    }

    if (subscriptionData.entity_afm) {
      return sub.subscription_type === 'entity' &&
             sub.entity === subscriptionData.entity_afm;
    }

    if (subscriptionData.relationship_org_uid && subscriptionData.relationship_entity_afm) {
      return sub.subscription_type === 'relationship' &&
             sub.relationship_org === subscriptionData.relationship_org_uid &&
             sub.relationship_entity === subscriptionData.relationship_entity_afm;
    }

    if (subscriptionData.person_name) {
      return (sub.subscription_type === 'person' || sub.subscription_type === 'signer') &&
             sub.person_name === subscriptionData.person_name;
    }

    if (subscriptionData.signer_name) {
      return sub.subscription_type === 'signer' &&
             sub.signer_name === subscriptionData.signer_name;
    }

    // Filter-only subscriptions
    if (subscriptionData.keywords || subscriptionData.amount_min ||
        subscriptionData.amount_max || subscriptionData.decision_types) {
      return sub.subscription_type === 'filter_only' &&
             JSON.stringify(sub.keywords) === JSON.stringify(subscriptionData.keywords) &&
             sub.amount_min === subscriptionData.amount_min &&
             sub.amount_max === subscriptionData.amount_max &&
             JSON.stringify(sub.decision_types) === JSON.stringify(subscriptionData.decision_types);
    }

    return false;
  }) || null;
}

/**
 * Toggle subscription for an entity
 * Uses the check endpoints to determine if subscription exists, then creates/deletes
 *
 * @param {Object} subscriptionData - Subscription data
 * @returns {Promise<Object>} Object with { action: 'created'|'deleted', subscription: Object }
 */
export async function toggleSubscription(subscriptionData) {
  let checkResult = null;

  // Determine which check endpoint to use based on subscription data
  if (subscriptionData.organization_uid) {
    checkResult = await checkOrganizationSubscription(subscriptionData.organization_uid);
  } else if (subscriptionData.entity_afm) {
    checkResult = await checkEntitySubscription(subscriptionData.entity_afm);
  } else if (subscriptionData.relationship_org_uid && subscriptionData.relationship_entity_afm) {
    checkResult = await checkRelationshipSubscription(
      subscriptionData.relationship_org_uid,
      subscriptionData.relationship_entity_afm
    );
  } else if (subscriptionData.signer_name) {
    checkResult = await checkSignerSubscription(subscriptionData.signer_name);
  } else if (subscriptionData.person_name) {
    // Person subscriptions use the signer check endpoint
    checkResult = await checkSignerSubscription(subscriptionData.person_name);
  } else {
    // For filter-only or other types, fall back to fetching all and comparing
    const subscriptions = await getSubscriptions();
    const existing = subscriptions.find(sub => {
      if (subscriptionData.keywords || subscriptionData.amount_min ||
          subscriptionData.amount_max || subscriptionData.decision_types) {
        return sub.subscription_type === 'filter_only' &&
               JSON.stringify(sub.keywords) === JSON.stringify(subscriptionData.keywords) &&
               sub.amount_min === subscriptionData.amount_min &&
               sub.amount_max === subscriptionData.amount_max &&
               JSON.stringify(sub.decision_types) === JSON.stringify(subscriptionData.decision_types);
      }
      return false;
    });
    checkResult = existing ? { subscribed: true, subscription: existing } : { subscribed: false, subscription: null };
  }

  if (checkResult && checkResult.subscribed && checkResult.subscription) {
    // Subscription exists - delete it
    await deleteSubscription(checkResult.subscription.id);
    return {
      action: 'deleted',
      subscription: checkResult.subscription
    };
  } else {
    // Subscription doesn't exist - create it
    const created = await createSubscription(subscriptionData);
    return { action: 'created', subscription: created };
  }
}

/**
 * Get subscription summary stats
 * @returns {Promise<Object>} Object with counts by type and total
 */
export async function getSubscriptionStats() {
  const subscriptions = await getSubscriptions();

  const stats = {
    total: subscriptions.length,
    by_type: {}
  };

  subscriptions.forEach(sub => {
    const type = sub.subscription_type;
    stats.by_type[type] = (stats.by_type[type] || 0) + 1;
  });

  return stats;
}
