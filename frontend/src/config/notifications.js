/**
 * Notification system configuration
 * Centralized configuration values for the notification system
 */

export const NOTIFICATION_CONFIG = {
  /**
   * Polling interval for unread count updates (in milliseconds)
   * Default: 10 minutes (600000ms)
   */
  UNREAD_COUNT_POLL_INTERVAL: 600000,

  /**
   * Default number of notifications to fetch per page
   */
  DEFAULT_PAGE_SIZE: 20,

  /**
   * Maximum number of notifications to show in the sidebar
   */
  MAX_SIDEBAR_NOTIFICATIONS: 50,

  /**
   * Valid pages where subscriptions are enabled
   * All other pages will have the notification button disabled
   * Paths support route parameter syntax (e.g., :id, :name)
   */
  VALID_SUBSCRIPTION_PAGES: [
    '/relationship/entity/:afm/org/:orgUid',
    '/entity/afm/:afm',
    '/entity/organization/:orgUid',
    '/entity/signer/:signerName',
    '/entity/person/:personName',
  ],
};

export default NOTIFICATION_CONFIG;
