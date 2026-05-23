import { useMemo } from 'react';
import { useLocation, matchPath } from 'react-router-dom';
import { NOTIFICATION_CONFIG } from '../config/notifications';
import { useTranslation } from '../contexts/TranslationContext';

/**
 * @typedef {Object} OrganizationContext
 * @property {'organization'} type
 * @property {string} organizationUid
 * @property {string} [organizationName]
 */

/**
 * @typedef {Object} EntityContext
 * @property {'entity'} type
 * @property {string} afm
 * @property {string} [entityName]
 */

/**
 * @typedef {Object} SignerContext
 * @property {'signer'} type
 * @property {string} signerName
 */

/**
 * @typedef {Object} RelationshipContext
 * @property {'relationship'} type
 * @property {string} organizationUid
 * @property {string} afm
 * @property {string} [organizationName]
 * @property {string} [entityName]
 */

/**
 * @typedef {Object} PersonContext
 * @property {'person'} type
 * @property {string} personName
 */

/**
 * @typedef {Object} PassiveContext
 * @property {'passive'} type - Pages where users can create free-form subscriptions (home, search, library)
 * @property {any} [metadata] - Optional metadata about the page
 */

/**
 * @typedef {Object} DisabledContext
 * @property {'disabled'} type - Pages where subscriptions are disabled (decision details, unit pages)
 * @property {string} [reason] - Reason why subscriptions are disabled (for hover text)
 */

/**
 * @typedef {OrganizationContext | EntityContext | SignerContext | RelationshipContext | PersonContext | PassiveContext | DisabledContext} NotificationContext
 */

/**
 * @typedef {Object} ContextCapabilities
 * @property {boolean} canSubscribe
 * @property {string|null} subscriptionType
 * @property {string} [suggestedName]
 */

/**
 * @typedef {Object} TargetData
 * @property {string} id
 * @property {string} name
 * @property {string} type
 */

/**
 * @typedef {Object} NotificationContextResult
 * @property {NotificationContext} context
 * @property {ContextCapabilities} capabilities
 * @property {boolean} isLoading
 * @property {TargetData} [targetData]
 */

/**
 * Detects the current page context and returns appropriate notification subscription information
 *
 * @param {Object} [options] - Optional configuration
 * @param {any} [options.entityData] - Entity data from page state (for entity pages)
 * @returns {NotificationContextResult}
 */
export function useNotificationContext(options = {}) {
    const location = useLocation();
    const { entityData } = options;
    const { t } = useTranslation();

    // Detect context from current route
    const context = useMemo(() => {
        return detectContextFromRoute(location.pathname, entityData, t);
    }, [location.pathname, entityData, t]);

    // Calculate capabilities based on context
    const capabilities = useMemo(() => {
        return getContextCapabilities(context);
    }, [context]);

    // Determine if we're waiting for entity data to load
    const isLoading = useMemo(() => {
        // If we're on a page that should have entity data but don't have it yet, we're loading
        const needsEntityData = ['organization', 'entity', 'signer', 'person', 'relationship'].includes(context.type);
        return needsEntityData && !entityData && !context.organizationName && !context.entityName && !context.signerName && !context.personName;
    }, [context, entityData]);

    // Build target data if available
    const targetData = useMemo(() => {
        if (!entityData) return undefined;

        switch (context.type) {
            case 'organization':
                return {
                    id: context.organizationUid,
                    name: entityData.label || entityData.name || context.organizationName || '',
                    type: 'organization',
                    ...entityData
                };

            case 'entity':
                return {
                    id: context.afm,
                    name: entityData.label || entityData.name || context.entityName || '',
                    type: 'entity',
                    ...entityData
                };

            case 'signer':
                return {
                    id: context.signerName,
                    name: entityData.label || entityData.name || context.signerName,
                    type: 'signer',
                    ...entityData
                };

            case 'person':
                return {
                    id: context.personName,
                    name: entityData.label || entityData.name || context.personName,
                    type: 'person',
                    ...entityData
                };

            case 'relationship':
                return {
                    id: `${context.organizationUid}_${context.afm}`,
                    name: `${context.organizationName || ''} × ${context.entityName || ''}`,
                    type: 'relationship',
                    organizationUid: context.organizationUid,
                    afm: context.afm,
                    ...entityData
                };

            default:
                return undefined;
        }
    }, [context, entityData]);

    return {
        context,
        capabilities,
        isLoading,
        targetData
    };
}

/**
 * Detects notification context from the current route
 *
 * @param {string} pathname - Current pathname
 * @param {any} [entityData] - Entity data from page state
 * @param {Function} t - Translation function
 * @returns {NotificationContext}
 */
function detectContextFromRoute(pathname, entityData, t) {
    // Check if the current page is in the whitelist of valid subscription pages
    const isValidPage = NOTIFICATION_CONFIG.VALID_SUBSCRIPTION_PAGES.some(validPath =>
        matchPath(validPath, pathname)
    );

    // If not in whitelist, return disabled
    if (!isValidPage) {
        // Special message for common pages
        if (pathname === '/' || matchPath('/', pathname)) {
            return {
                type: 'disabled',
                reason: t('notifications.disabledOnHomePage')
            };
        }
        if (matchPath('/decision/:ada', pathname)) {
            return {
                type: 'disabled',
                reason: t('notifications.disabledOnDecisionPage')
            };
        }
        return {
            type: 'disabled',
            reason: t('notifications.disabledOnThisPage')
        };
    }

    // Match patterns in order of specificity

    // Relationship page: /relationship/entity/:afm/org/:orgUid
    const relationshipMatch = matchPath('/relationship/entity/:afm/org/:orgUid', pathname);
    if (relationshipMatch) {
        return {
            type: 'relationship',
            organizationUid: relationshipMatch.params.orgUid,
            afm: relationshipMatch.params.afm,
            organizationName: entityData?.organization?.label || entityData?.organization?.name,
            entityName: entityData?.entity?.label || entityData?.entity?.name
        };
    }

    // AFM Entity page: /entity/afm/:afm
    const afmEntityMatch = matchPath('/entity/afm/:afm', pathname);
    if (afmEntityMatch) {
        return {
            type: 'entity',
            afm: afmEntityMatch.params.afm,
            entityName: entityData?.label || entityData?.name
        };
    }

    // Generic Entity page: /entity/:entityType/:entityId
    const entityMatch = matchPath('/entity/:entityType/:entityId', pathname);
    if (entityMatch) {
        const { entityType, entityId } = entityMatch.params;

        // Organization
        if (entityType === 'organization') {
            return {
                type: 'organization',
                organizationUid: entityId,
                organizationName: entityData?.label || entityData?.name
            };
        }

        // Signer
        if (entityType === 'signer') {
            return {
                type: 'signer',
                signerName: decodeURIComponent(entityId),
            };
        }

        // Person
        if (entityType === 'person') {
            return {
                type: 'person',
                personName: decodeURIComponent(entityId),
            };
        }

        // Unit pages - disabled (not in whitelist, but explicit handling)
        if (entityType === 'unit') {
            return {
                type: 'disabled',
                reason: t('notifications.disabledOnThisPage')
            };
        }

        // Unknown entity type - treat as disabled for safety
        return {
            type: 'disabled',
            reason: t('notifications.disabledOnThisPage')
        };
    }

    // Fallback: Should not reach here if whitelist is properly maintained
    console.warn('Valid page pattern matched but no specific handler found:', pathname);
    return {
        type: 'disabled',
        reason: t('notifications.disabledOnThisPage')
    };
}

/**
 * Calculates context capabilities (whether user can subscribe, etc.)
 *
 * @param {NotificationContext} context
 * @returns {ContextCapabilities}
 */
function getContextCapabilities(context) {
    switch (context.type) {
        case 'organization':
            return {
                canSubscribe: true,
                subscriptionType: 'organization',
                suggestedName: context.organizationName || `Organization ${context.organizationUid}`
            };

        case 'entity':
            return {
                canSubscribe: true,
                subscriptionType: 'entity',
                suggestedName: context.entityName || `Entity ${context.afm}`
            };

        case 'signer':
            return {
                canSubscribe: true,
                subscriptionType: 'signer',
                suggestedName: context.signerName
            };

        case 'person':
            return {
                canSubscribe: true,
                subscriptionType: 'person',
                suggestedName: context.personName
            };

        case 'relationship':
            return {
                canSubscribe: true,
                subscriptionType: 'relationship',
                suggestedName: `${context.organizationName || 'Organization'} × ${context.entityName || 'Entity'}`
            };

        case 'passive':
            return {
                canSubscribe: false,
                subscriptionType: null
            };

        case 'disabled':
            return {
                canSubscribe: false,
                subscriptionType: null
            };

        default:
            return {
                canSubscribe: false,
                subscriptionType: null
            };
    }
}

export default useNotificationContext;
