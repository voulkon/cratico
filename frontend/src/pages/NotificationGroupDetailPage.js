import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import {
  getNotificationGroup,
  getGroupDecisions,
  getNotificationGroupSummary,
  markGroupRead,
} from '../api/notifications';
import apiClient from '../api/client';
import { formatAmount } from '../utils/dateUtils';
import './NotificationBatchDetailPage.css';

import DecisionList from '../components/DecisionList';
import DecisionsToolbar from '../components/DecisionsToolbar';
import BatchMetadataHeader from '../components/BatchMetadataHeader';
import AISummaryCard from '../components/AISummaryCard';
import TopBarSlot from '../components/TopBarSlot';
import { ChartIcon } from '../components/Icons';

/**
 * Page for a presentation/email notification group.
 *
 * Groups own no AI fields: generation stays per batch at detection time and
 * the summary card reads a read-only composition of the batches plus the
 * shared one-liner cache.
 */
const NotificationGroupDetailPage = () => {
  const { groupId } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const [group, setGroup] = useState(null);
  useDocumentTitle(group?.display_name || `Group ${groupId}`);
  const [decisions, setDecisions] = useState([]);
  const [pagination, setPagination] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  const [sortBy, setSortBy] = useState('recent');
  const [isViewedFilter, setIsViewedFilter] = useState(null);

  const [aiSummary, setAiSummary] = useState(null);
  const pollTimerRef = useRef(null);

  useEffect(() => {
    const fetchGroupData = async () => {
      try {
        setLoading(true);
        setError(null);

        const groupData = await getNotificationGroup(groupId);
        setGroup(groupData);

        if (!groupData.is_read) {
          await markGroupRead(groupId);
          groupData.is_read = true;
        }

        const decisionsData = await getGroupDecisions(
          groupId,
          1,
          20,
          isViewedFilter,
          sortBy
        );
        setDecisions(decisionsData.results || []);
        setPagination({
          current_page: 1,
          total_count: decisionsData.count,
          has_next: decisionsData.has_next || !!decisionsData.next,
          has_previous: !!decisionsData.previous,
        });
      } catch (err) {
        console.error('Error fetching group data:', err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    if (groupId) {
      fetchGroupData();
    }
  }, [groupId, isViewedFilter, sortBy]);

  const pollSummary = useCallback(async () => {
    if (!groupId) return;
    try {
      const data = await getNotificationGroupSummary(groupId);
      setAiSummary(data);
      if (data.status === 'RUNNING') {
        pollTimerRef.current = setTimeout(pollSummary, 5000);
      }
    } catch (err) {
      // Summary endpoint unavailable — ignore
    }
  }, [groupId]);

  useEffect(() => {
    pollSummary();
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, [pollSummary]);

  const handleLoadMore = async () => {
    if (!pagination?.has_next || loadingMore) return;

    try {
      setLoadingMore(true);
      const nextPage = pagination.current_page + 1;
      const decisionsData = await getGroupDecisions(
        groupId,
        nextPage,
        20,
        isViewedFilter,
        sortBy
      );

      setDecisions((prev) => [...prev, ...(decisionsData.results || [])]);
      setPagination({
        current_page: nextPage,
        total_count: decisionsData.count,
        has_next: decisionsData.has_next || !!decisionsData.next,
        has_previous: !!decisionsData.previous,
      });
    } catch (err) {
      console.error('Error loading more decisions:', err);
    } finally {
      setLoadingMore(false);
    }
  };

  const handleViewDocumentContent = async (decisionAda) => {
    const response = await apiClient.get(`/decision/${decisionAda}/content/`);
    return response.data;
  };

  // Generation stays per batch, at detection time.  "Generate" opens the
  // oldest batch that still lacks a complete summary.
  const handleGenerate = () => {
    const target = (group?.batches || []).find(
      (batch) => batch.ai_summary_status !== 'COMPLETED'
    );
    if (target) {
      navigate(`/batch/${target.id}`);
    }
  };

  const formatDate = (dateString) => {
    if (!dateString) return 'N/A';
    return new Date(dateString).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (loading && !group) {
    return (
      <div className="notification-batch-detail-page">
        <div className="loading-container">
          <div className="loading-spinner" />
          <p>{t('notifications.loadingGroup')}</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="notification-batch-detail-page">
        <div className="error-container">
          <h2>{t('notifications.errorLoadingGroup')}</h2>
          <p>{error}</p>
          <button onClick={() => navigate('/notifications')} className="back-button">
            {t('common.goBack')}
          </button>
        </div>
      </div>
    );
  }

  if (!group) {
    return (
      <div className="notification-batch-detail-page">
        <div className="not-found-container">
          <h2>{t('notifications.groupNotFound')}</h2>
          <button onClick={() => navigate('/notifications')} className="back-button">
            {t('common.goBack')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="notification-batch-detail-page">
      <TopBarSlot>
        <div className="batch-header-topbar">
          <span className="batch-title-topbar">
            {t('notifications.notificationGroup')} #{groupId}
          </span>
          {group.display_name && (
            <>
              <span className="batch-topbar-sep">·</span>
              <span className="batch-subscription-topbar">
                {group.display_name}
              </span>
            </>
          )}
        </div>
      </TopBarSlot>

      <nav className="breadcrumb">
        <button onClick={() => navigate('/notifications')} className="breadcrumb-link">
          {t('navigation.notifications')}
        </button>
        <span className="breadcrumb-separator">›</span>
        <span className="breadcrumb-current">
          {t('notifications.notificationGroup')} #{groupId}
        </span>
      </nav>

      <BatchMetadataHeader
        batch={{
          subscription: group.subscription,
          check_window_end: group.period_end,
          decision_publish_start: group.decision_publish_start,
          decision_publish_end: group.decision_publish_end,
          created_at: group.created_at,
          match_count: group.total_match_count,
          aggregate_stats: {},
        }}
        formatDate={formatDate}
        formatAmount={formatAmount}
        showCheckWindow={true}
        showCreatedAt={true}
        showSubscriptionInfo={true}
        showStats={false}
        title={t('notifications.notificationGroup')}
      />

      {group.subscription && (
        <div className="subscription-link-container">
          <button
            className="view-all-subscription-link"
            onClick={() =>
              navigate(
                `/notifications/subscriptions/${group.subscription.id}/history`
              )
            }
          >
            <ChartIcon size={18} />
            {t('notifications.viewAllFromSubscription')}
          </button>
        </div>
      )}

      <AISummaryCard
        summary={aiSummary}
        onGenerate={handleGenerate}
        triggering={false}
      />

      <DecisionsToolbar
        title={t('notifications.decisions', 'Decisions')}
        totalCount={pagination?.total_count}
        viewedFilter={isViewedFilter}
        onViewedFilterChange={setIsViewedFilter}
        sortBy={sortBy}
        onSortChange={setSortBy}
        sortVariant="simple"
        pagination={pagination}
      >
        <DecisionList
          decisions={decisions.map((bd) => ({
            ...bd.decision,
            _batchDecisionId: bd.id,
            _isViewed: bd.is_viewed,
          }))}
          loading={loading}
          loadingMore={loadingMore}
          pagination={pagination}
          formatAmount={formatAmount}
          onViewDocumentContent={handleViewDocumentContent}
          onLoadMore={handleLoadMore}
          emptyMessage={t('notifications.noDecisionsInBatch')}
          infiniteScroll={true}
          getDecisionKey={(d) => `group-${groupId}-${d._batchDecisionId || d.id}`}
        />
      </DecisionsToolbar>
    </div>
  );
};

export default NotificationGroupDetailPage;
