import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getSubscription,
  getSubscriptionAllDecisions
} from '../api/notifications';
import apiClient from '../api/client';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import './SubscriptionHistoryPage.css';

// Import shared components
import DecisionListView from '../components/DecisionListView';
import SubscriptionMetadataHeader from '../components/SubscriptionMetadataHeader';
import { formatAmount } from '../utils/format';

/**
 * Page showing all decisions from a subscription across all batches
 */
const SubscriptionHistoryPage = () => {
  const { subscriptionId } = useParams();
  const navigate = useNavigate();

  // State
  const [subscription, setSubscription] = useState(null);
  useDocumentTitle(subscription?.name || 'Subscription History');
  const [decisions, setDecisions] = useState([]);
  const [metadata, setMetadata] = useState(null);
  const [pagination, setPagination] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  // Filters
  const [sortBy, setSortBy] = useState('recent');
  const [isViewedFilter, setIsViewedFilter] = useState(null);

  // Fetch subscription and all its decisions
  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        setError(null);

        // Fetch subscription details and all decisions in parallel
        const [subscriptionData, decisionsResponse] = await Promise.all([
          getSubscription(subscriptionId),
          getSubscriptionAllDecisions(subscriptionId, 1, 20, isViewedFilter, sortBy)
        ]);

        setSubscription(subscriptionData);
        setDecisions(decisionsResponse.results || []);
        setMetadata(decisionsResponse.metadata);
        setPagination({
          has_next: decisionsResponse.has_next || decisionsResponse.next !== null,
          total_count: decisionsResponse.count,
          current_page: 1
        });
      } catch (err) {
        console.error('Error fetching subscription history:', err);
        setError(err.message || 'Failed to load subscription history');
      } finally {
        setLoading(false);
      }
    };

    if (subscriptionId) {
      fetchData();
    }
  }, [subscriptionId, isViewedFilter, sortBy]);

  // Load more handler
  const handleLoadMore = async () => {
    if (!pagination?.has_next || loadingMore) return;

    try {
      setLoadingMore(true);
      const nextPage = (pagination.current_page || 1) + 1;

      const response = await getSubscriptionAllDecisions(
        subscriptionId,
        nextPage,
        20,
        isViewedFilter,
        sortBy
      );

      setDecisions(prev => [...prev, ...(response.results || [])]);
      setPagination(prev => ({
        ...prev,
        has_next: response.has_next || response.next !== null,
        current_page: nextPage
      }));
    } catch (err) {
      console.error('Error loading more decisions:', err);
    } finally {
      setLoadingMore(false);
    }
  };

  // View document content handler
  const handleViewDocumentContent = async (decisionAda) => {
    try {
      const response = await apiClient.get(`/decision/${decisionAda}/content/`);
      return response.data;
    } catch (error) {
      console.error('Error fetching document content:', error);
      throw error;
    }
  };

  // Format date helper
  const formatDate = (dateString) => {
    if (!dateString) return 'N/A';
    return new Date(dateString).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  // Loading state
  if (loading && !subscription) {
    return (
      <div className="subscription-history-page">
        <div className="loading-container">
          <div className="loading-spinner"></div>
          <p>Loading subscription history...</p>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="subscription-history-page">
        <div className="error-container">
          <h2>Error Loading Subscription History</h2>
          <p>{error}</p>
          <button onClick={() => navigate('/notifications')}>
            Back to Notifications
          </button>
        </div>
      </div>
    );
  }

  // Not found state
  if (!subscription) {
    return (
      <div className="subscription-history-page">
        <div className="not-found-container">
          <h2>Subscription Not Found</h2>
          <button onClick={() => navigate('/notifications')}>
            Back to Notifications
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="subscription-history-page">
      {/* Breadcrumb */}
      <nav className="breadcrumb">
        <button onClick={() => navigate('/notifications')} className="breadcrumb-link">
          Notifications
        </button>
        <span className="breadcrumb-separator">›</span>
        <button onClick={() => navigate('/notifications/subscriptions')} className="breadcrumb-link">
          Subscriptions
        </button>
        <span className="breadcrumb-separator">›</span>
        <span className="breadcrumb-current">
          {subscription.alias || `Subscription #${subscriptionId}`}
        </span>
      </nav>

      {/* Subscription Metadata Header */}
      <SubscriptionMetadataHeader
        subscription={subscription}
        totalBatches={metadata?.total_batches}
        totalDecisions={pagination?.total_count}
        dateRange={metadata?.date_range}
        formatDate={formatDate}
        formatAmount={formatAmount}
        title="Subscription History"
      />

      {/* Decision List */}
      <DecisionListView
        decisions={decisions}
        loading={loading}
        loadingMore={loadingMore}
        pagination={pagination}
        sortBy={sortBy}
        onSortChange={setSortBy}
        showViewedFilter={true}
        isViewedFilter={isViewedFilter}
        onViewedFilterChange={setIsViewedFilter}
        onLoadMore={handleLoadMore}
        onViewDocumentContent={handleViewDocumentContent}
        formatAmount={formatAmount}
        emptyMessage="No decisions found for this subscription yet. Check back after the next scheduled run."
        decisionKeyPrefix={`sub-${subscriptionId}`}
      />
    </div>
  );
};

export default SubscriptionHistoryPage;
