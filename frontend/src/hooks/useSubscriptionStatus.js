import { useState, useEffect, useCallback } from 'react';
import {
  checkOrganizationSubscription,
  checkEntitySubscription,
  checkRelationshipSubscription,
  checkSignerSubscription
} from '../api/notifications';
import { useAuth } from '../contexts/AuthContext';

/**
 * Hook to check if the user is subscribed to the current context
 * @param {Object} context - Notification context from useNotificationContext
 * @returns {{ subscribed: boolean, subscription: Object|null, isLoading: boolean, refetch: Function }}
 */
export function useSubscriptionStatus(context) {
  const [subscribed, setSubscribed] = useState(false);
  const [subscription, setSubscription] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const { isSignedIn, isLoaded } = useAuth();

  const checkSubscription = useCallback(async () => {
    // Don't check if user is not signed in
    if (!isSignedIn) {
      setSubscribed(false);
      setSubscription(null);
      setIsLoading(false);
      return;
    }

    // Don't check for passive or disabled contexts
    if (!context || context.type === 'passive' || context.type === 'disabled') {
      setSubscribed(false);
      setSubscription(null);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    try {
      let result = null;

      switch (context.type) {
        case 'organization':
          if (context.organizationUid) {
            result = await checkOrganizationSubscription(context.organizationUid);
          }
          break;

        case 'entity':
          if (context.afm) {
            result = await checkEntitySubscription(context.afm);
          }
          break;

        case 'relationship':
          if (context.organizationUid && context.afm) {
            result = await checkRelationshipSubscription(context.organizationUid, context.afm);
          }
          break;

        case 'signer':
          if (context.signerName) {
            result = await checkSignerSubscription(context.signerName);
          }
          break;

        case 'person':
          if (context.personName) {
            result = await checkSignerSubscription(context.personName);
          }
          break;

        default:
          break;
      }

      if (result) {
        setSubscribed(result.subscribed || false);
        setSubscription(result.subscription || null);
      } else {
        setSubscribed(false);
        setSubscription(null);
      }
    } catch (error) {
      console.error('Failed to check subscription status:', error);
      setSubscribed(false);
      setSubscription(null);
    } finally {
      setIsLoading(false);
    }
  }, [context, isSignedIn]);

  useEffect(() => {
    if (isLoaded) {
      checkSubscription();
    }
  }, [checkSubscription, isLoaded]);

  return {
    subscribed,
    subscription,
    isLoading,
    refetch: checkSubscription
  };
}

export default useSubscriptionStatus;
