import React from 'react';
import DecisionCard from './DecisionCard';
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
}) => {
  const defaultGetKey = (decision) => decision.ada || decision.id;
  const resolveKey = getDecisionKey || defaultGetKey;

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

  return (
    <div className="decisions-list">
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

      {pagination?.has_next && (
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
    </div>
  );
};

export default DecisionList;
