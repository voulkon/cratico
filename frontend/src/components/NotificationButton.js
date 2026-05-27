import React, { useState } from 'react';
import { Bell, Loader2 } from 'lucide-react';
import SplitButton from './SplitButton';
import { useNotificationContext } from '../hooks/useNotificationContext';
import { useUnreadCount } from '../hooks/useUnreadCount';
import { useSubscriptionStatus } from '../hooks/useSubscriptionStatus';
import { toggleSubscription } from '../api/notifications';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from '../contexts/TranslationContext';
import './NotificationButton.css';

/**
 * Split notification button for TopControls.
 * Left half: bell icon that:
 *   - On subscribable pages: toggles subscription for current entity
 *   - On passive pages: opens notification sidebar
 *   - On disabled pages: shows disabled state with tooltip
 * Right half: chevron opens/closes the notification sidebar.
 */
export default function NotificationButton({ onSidebarToggle, isSidebarOpen }) {
  const { context, capabilities } = useNotificationContext();
  const { unreadCount, isLoading: countLoading } = useUnreadCount(); // Uses default from config
  const { subscribed, isLoading: subLoading, refetch: refetchSubscription } = useSubscriptionStatus(context);
  const { isSignedIn } = useAuth();
  const { t } = useTranslation();

  const [isActionLoading, setIsActionLoading] = useState(false);
  const [showToast, setShowToast] = useState(false);
  const [toastMessage, setToastMessage] = useState('');

  const isLoading = countLoading || subLoading || isActionLoading;

  // Build tooltip text based on context
  const getTooltipText = () => {
    if (!isSignedIn) {
      return t('auth.signInToSubscribe') || 'Sign in to subscribe to notifications';
    }

    if (context.type === 'disabled') {
      return context.reason || 'Subscriptions not available on this page';
    }

    if (context.type === 'passive') {
      return 'Open notifications';
    }

    if (isLoading) {
      return 'Loading...';
    }

    if (subscribed) {
      return `Unsubscribe from ${capabilities.suggestedName || 'notifications'}`;
    }

    return `Subscribe to ${capabilities.suggestedName || 'notifications'}`;
  };

  // Get chevron tooltip text
  const getChevronTooltipText = () => {
    if (!isSignedIn) {
      return t('auth.signInToSubscribe') || 'Sign in to view notifications';
    }
    return isSidebarOpen ? 'Close notifications' : 'Open notifications';
  };

  // Handle bell click (subscribe/unsubscribe or open sidebar)
  const handleBellClick = async () => {
    // Not signed in - prompt to sign in
    if (!isSignedIn) {
      window.dispatchEvent(new CustomEvent('authRequired', {
        detail: {
          supertitle: t('auth.signInToSubscribe') || 'This feature requires sign-in.',
          message: t('auth.NotificationSignInExplanation') || 'Please sign in to create notification rules and receive updates about new decisions that match your interests.'
        }
      }));
      return;
    }

    // Disabled pages - do nothing
    if (context.type === 'disabled') {
      return;
    }

    // Passive pages - open sidebar
    if (context.type === 'passive') {
      handleToggleSidebar();
      return;
    }

    // Subscribable pages - toggle subscription
    if (capabilities.canSubscribe) {
      setIsActionLoading(true);
      try {
        const subscriptionData = buildSubscriptionData(context);
        const result = await toggleSubscription(subscriptionData);

        // Refetch subscription status
        await refetchSubscription();

        // Show toast
        const action = result.action === 'created' ? 'subscribed' : 'unsubscribed';
        const message = action === 'subscribed'
          ? `Subscribed to ${capabilities.suggestedName}`
          : `Unsubscribed from ${capabilities.suggestedName}`;

        setToastMessage(message);
        setShowToast(true);
        setTimeout(() => setShowToast(false), 3000);
      } catch (error) {
        console.error('Failed to toggle subscription:', error);

        // Extract error message from response
        let errorMessage = 'Failed to update subscription';
        if (error.response?.data?.error) {
          errorMessage = error.response.data.error;
        } else if (error.response?.data?.detail) {
          errorMessage = error.response.data.detail;
        } else if (error.message) {
          errorMessage = error.message;
        }

        setToastMessage(errorMessage);
        setShowToast(true);
        setTimeout(() => setShowToast(false), 3000);
      } finally {
        setIsActionLoading(false);
      }
    }
  };

  // Handle chevron click (toggle sidebar)
  const handleToggleSidebar = () => {
    if (!isSignedIn) {
      window.dispatchEvent(new CustomEvent('authRequired', {
        detail: {
          supertitle: t('auth.signInToSubscribe') || 'This feature requires sign-in.',
          message: t('auth.NotificationSignInExplanation') || 'Please sign in to create notification rules and receive updates about new decisions that match your interests.'
        }
      }));
      return;
    }
    onSidebarToggle?.(!isSidebarOpen);
  };

  // Build subscription data from context
  const buildSubscriptionData = (ctx) => {
    const data = {};

    switch (ctx.type) {
      case 'organization':
        data.organization_uid = ctx.organizationUid;
        break;
      case 'entity':
        data.entity_afm = ctx.afm;
        break;
      case 'signer':
        data.signer_name = ctx.signerName;
        break;
      case 'person':
        data.person_name = ctx.personName;
        break;
      case 'relationship':
        data.relationship_org_uid = ctx.organizationUid;
        data.relationship_entity_afm = ctx.afm;
        break;
      default:
        break;
    }

    return data;
  };

  // Format unread count for display
  const formatCount = (count) => {
    if (count === 0) return null;
    if (count > 99) return '99+';
    return count;
  };

  const displayCount = formatCount(unreadCount);
  const isDisabled = context.type === 'disabled';
  const isAuthRequired = !isSignedIn;

  return (
    <>
      <SplitButton
        isOpen={isSidebarOpen}
        onMainClick={handleBellClick}
        onChevronClick={handleToggleSidebar}
        mainActive={subscribed}
        mainClassName={`notification-button ${isLoading ? 'loading' : ''} ${isDisabled ? 'disabled' : ''} ${isAuthRequired ? 'auth-required' : ''}`}
        chevronClassName={`notification-chevron ${isAuthRequired ? 'auth-required' : ''}`}
        className={`notification-split-btn ${isSidebarOpen ? 'sidebar-open' : ''}`}
        mainTitle={getTooltipText()}
        chevronTitle={getChevronTooltipText()}
        mainDisabled={isAuthRequired ? false : (isDisabled || isLoading)}
        chevronDisabled={false}
        badge={isAuthRequired ? null : displayCount}
      >
        <span className="notification-icon" data-testid="bell-icon">
          {isLoading ? <Loader2 className="icon-spin" size={18} /> : <Bell size={18} />}
        </span>
      </SplitButton>

      {/* Toast notification */}
      {showToast && (
        <div className="notification-toast">
          {toastMessage}
        </div>
      )}
    </>
  );
}
