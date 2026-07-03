import React, { useRef } from 'react';
import DecisionCard from './DecisionCard';
import useInfiniteScroll from '../hooks/useInfiniteScroll';
import './DecisionList.css';

const DecisionList = ({
  decisions,
  loading,
  loadingMore,
  error,
  pagination,
  hasSearchQuery,
  formatAmount,
  onViewDocumentContent,
  onLoadMore,
  emptyMessage = 'No decisions found',
  emptyFilterMessage = 'No decisions match filters',
  showPaginationInfo = false,
  getDecisionKey,
  showCount = false,
  countLabel = 'Decisions',
  hideLoadMore = false,
  infiniteScroll = false,
  scrollMaxHeight = 'calc(100vh - 200px)',
}) => {
  const scrollContainerRef = useRef(null);
  const defaultGetKey = (decision) => decision.ada || decision.id;
  const resolveKey = getDecisionKey || defaultGetKey;

  // ── Internal infinite scroll (when scroll container is inside this component) ──
  const { sentinelRef } = useInfiniteScroll({
    hasMore: infiniteScroll ? (pagination?.has_next ?? false) : false,
    loading,
    loadingMore,
    onLoadMore,
    rootRef: infiniteScroll ? scrollContainerRef : null,
    enabled: infiniteScroll,
  });

  if (loading && decisions.length === 0) {
    return <div className="decision-list-loading">{/* skeleton placeholder */}</div>;
  }

  if (error) {
    return (
      <div className="decision-list-error">
        <span>{error}</span>
      </div>
    );
  }

  if (decisions.length === 0) {
    return (
      <div className="no-decisions-message">
        {hasSearchQuery ? emptyFilterMessage : emptyMessage}
      </div>
    );
  }

  const listContent = (
    <>
      {showCount && (
        <div className="decisions-header">
          <h3 className="decisions-title">
            {countLabel}{' '}
            <span className="count-badge">
              {(pagination?.total_count ?? decisions.length).toLocaleString()}
            </span>
          </h3>
        </div>
      )}

      {decisions.map((decision, index) => (
        <DecisionCard
          key={resolveKey(decision)}
          decision={decision}
          formatAmount={formatAmount}
          index={index}
          isLastItem={index === decisions.length - 1}
          onViewDocumentContent={onViewDocumentContent}
        />
      ))}

      {loadingMore && (
        <div className="loading-more-container">
          <div className="loading-more-text" />
        </div>
      )}

      {showPaginationInfo && pagination && (
        <div className="pagination-info">
          {decisions.length} / {pagination.total_count ?? pagination.total_items}
        </div>
      )}

      {/* Sentinel for internal infinite scroll */}
      {infiniteScroll && <div ref={sentinelRef} className="scroll-sentinel" />}

      {/* Manual "Load more" button (only when NOT using infinite scroll) */}
      {!infiniteScroll && !hideLoadMore && pagination?.has_next && (
        <div className="load-more-container">
          <button
            onClick={onLoadMore}
            disabled={loadingMore}
            className={`load-more-button${loadingMore ? ' loading' : ''}`}
          >
            {loadingMore ? '…' : `Load more (${(pagination.total_count ?? pagination.total_items) - decisions.length} remaining)`}
          </button>
        </div>
      )}
    </>
  );

  // ── Wrap in a scrollable container when infiniteScroll is active ──
  if (infiniteScroll) {
    return (
      <div
        ref={scrollContainerRef}
        className="decisions-list decisions-list--scrollable"
        style={{ maxHeight: scrollMaxHeight, overflowY: 'auto' }}
      >
        {listContent}
      </div>
    );
  }

  return <div className="decisions-list">{listContent}</div>;
};

export default DecisionList;
