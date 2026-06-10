import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { getNotificationBatch, getBatchDecisions, markBatchRead } from '../api/notifications';
import apiClient from '../api/client';
import { formatAmount } from '../utils/dateUtils';
import './NotificationBatchDetailPage.css';

// Import shared components
import DecisionListView from '../components/DecisionListView';
import BatchMetadataHeader from '../components/BatchMetadataHeader';
import { ChartIcon } from '../components/Icons';

/**
 * Page for viewing details of a single notification batch and its decisions
 */
const NotificationBatchDetailPage = () => {
  const { batchId } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();

  // State
  const [batch, setBatch] = useState(null);
  useDocumentTitle(batch?.title || `Batch ${batchId}`);
  const [decisions, setDecisions] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  // Filters
  const [sortBy, setSortBy] = useState('recent');
  const [isViewedFilter, setIsViewedFilter] = useState(null); // null, true, or false

  // Fetch batch data
  useEffect(() => {
    const fetchBatchData = async () => {
      try {
        setLoading(true);
        setError(null);

        // Get batch details
        const batchData = await getNotificationBatch(batchId);
        setBatch(batchData);

        // Auto-mark as read if not already
        if (!batchData.is_read) {
          await markBatchRead(batchId);
          batchData.is_read = true;
        }

        // Get batch decisions (paginated) with sorting
        const decisionsData = await getBatchDecisions(batchId, 1, 20, isViewedFilter, sortBy);
        setDecisions(decisionsData.results || []);
        setPagination({
          current_page: 1,
          total_count: decisionsData.count,
          has_next: decisionsData.has_next || !!decisionsData.next,
          has_previous: !!decisionsData.previous
        });

      } catch (err) {
        console.error('Error fetching batch data:', err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    if (batchId) {
      fetchBatchData();
    }
  }, [batchId, isViewedFilter, sortBy]);

  // Load more handler
  const handleLoadMore = async () => {
    if (!pagination?.has_next || loadingMore) return;

    try {
      setLoadingMore(true);
      const nextPage = pagination.current_page + 1;
      const decisionsData = await getBatchDecisions(batchId, nextPage, 20, isViewedFilter, sortBy);

      setDecisions(prev => [...prev, ...(decisionsData.results || [])]);
      setPagination({
        current_page: nextPage,
        total_count: decisionsData.count,
        has_next: decisionsData.has_next || !!decisionsData.next,
        has_previous: !!decisionsData.previous
      });
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
  if (loading && !batch) {
    return (
      <div className="notification-batch-detail-page">
        <div className="loading-container">
          <div className="loading-spinner"></div>
          <p>{t('notifications.loadingBatch')}</p>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="notification-batch-detail-page">
        <div className="error-container">
          <h2>{t('notifications.errorLoadingBatch')}</h2>
          <p>{error}</p>
          <button onClick={() => navigate('/notifications')} className="back-button">
            {t('common.goBack')}
          </button>
        </div>
      </div>
    );
  }

  // Not found state
  if (!batch) {
    return (
      <div className="notification-batch-detail-page">
        <div className="not-found-container">
          <h2>{t('notifications.batchNotFound')}</h2>
          <button onClick={() => navigate('/notifications')} className="back-button">
            {t('common.goBack')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="notification-batch-detail-page">
      {/* Breadcrumb */}
      <nav className="breadcrumb">
        <button onClick={() => navigate('/notifications')} className="breadcrumb-link">
          {t('navigation.notifications')}
        </button>
        <span className="breadcrumb-separator">›</span>
        <span className="breadcrumb-current">
          {t('notifications.batch')} #{batchId}
        </span>
      </nav>

      {/* Batch Metadata Header - Now using shared component */}
      <BatchMetadataHeader
        batch={batch}
        formatDate={formatDate}
        formatAmount={formatAmount}
        showCheckWindow={true}
        showCreatedAt={true}
        showSubscriptionInfo={true}
        showStats={true}
      />

      {/* Link to view all subscription decisions */}
      {batch.subscription && (
        <div className="subscription-link-container">
          <button
            className="view-all-subscription-link"
            onClick={() => navigate(`/notifications/subscriptions/${batch.subscription.id}/history`)}
          >
            <ChartIcon size={18} />
            {t('notifications.viewAllFromSubscription')}
          </button>
        </div>
      )}

      {/* Decision List - Now using shared component */}
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
        emptyMessage={t('notifications.noDecisionsInBatch')}
        decisionKeyPrefix={`batch-${batchId}`}
      />
    </div>
  );
};

export default NotificationBatchDetailPage;
