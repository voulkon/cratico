import React from 'react';
import PropTypes from 'prop-types';
import DecisionCard from './DecisionCard';
import SortControl from './SortControl';
import './DecisionListView.css';

/**
 * Shared component for displaying a list of decisions with pagination,
 * sorting, and filtering capabilities.
 *
 * Used by:
 * - NotificationBatchDetailPage
 * - SubscriptionHistoryPage
 */
const DecisionListView = ({
  decisions,
  loading,
  loadingMore,
  pagination,
  sortBy,
  onSortChange,
  showViewedFilter = false,
  isViewedFilter = null,
  onViewedFilterChange,
  onLoadMore,
  onViewDocumentContent,
  formatAmount,
  emptyMessage = 'No decisions found',
  decisionKeyPrefix = 'decision'
}) => {
  return (
    <div className="decision-list-view">
      {/* Controls Header */}
      <div className="decisions-header">
        <h3 className="decisions-title">
          {pagination?.total_count !== undefined ? (
            <>
              Decisions{' '}
              <span className="count-badge">
                {pagination.total_count.toLocaleString()}
              </span>
            </>
          ) : (
            'Decisions'
          )}
        </h3>

        <div className="controls-container">
          {/* Viewed Filter */}
          {showViewedFilter && (
            <div className="viewed-filter">
              <label htmlFor="viewed-filter" className="sort-label">Filter:</label>
              <select
                id="viewed-filter"
                className="sort-select"
                value={isViewedFilter === null ? 'all' : isViewedFilter.toString()}
                onChange={(e) => {
                  const value = e.target.value;
                  if (value === 'all') {
                    onViewedFilterChange(null);
                  } else {
                    onViewedFilterChange(value === 'true');
                  }
                }}
              >
                <option value="all">All Decisions</option>
                <option value="false">Unviewed Only</option>
                <option value="true">Viewed Only</option>
              </select>
            </div>
          )}

          {/* Sort Control */}
          <SortControl
            sortBy={sortBy}
            onSortChange={onSortChange}
          />
        </div>
      </div>

      {/* Loading State */}
      {loading && decisions.length === 0 ? (
        <div className="loading-text">Loading decisions...</div>
      ) : decisions.length === 0 ? (
        <div className="no-decisions-message">{emptyMessage}</div>
      ) : (
        <>
          {/* Decisions List */}
          <div className="decisions-list">
            {decisions.map((batchDecision, index) => (
              <DecisionCard
                key={`${decisionKeyPrefix}-${batchDecision.id || index}`}
                decision={batchDecision.decision}
                formatAmount={formatAmount}
                onViewDocumentContent={onViewDocumentContent}
                isViewed={batchDecision.is_viewed}
                matchDetails={batchDecision.match_details}
                batchDecisionId={batchDecision.id}
              />
            ))}
          </div>

          {/* Load More Button */}
          {pagination?.has_next && (
            <div className="load-more-container">
              <button
                onClick={onLoadMore}
                disabled={loadingMore}
                className={`load-more-button ${loadingMore ? 'loading' : ''}`}
              >
                {loadingMore ? 'Loading...' : 'Load More Decisions'}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
};

DecisionListView.propTypes = {
  // Data
  decisions: PropTypes.arrayOf(PropTypes.shape({
    id: PropTypes.number,
    decision: PropTypes.object.isRequired,
    is_viewed: PropTypes.bool,
    match_details: PropTypes.object
  })).isRequired,

  loading: PropTypes.bool,
  loadingMore: PropTypes.bool,

  // Pagination
  pagination: PropTypes.shape({
    has_next: PropTypes.bool,
    total_count: PropTypes.number,
    current_page: PropTypes.number
  }),

  // Sorting
  sortBy: PropTypes.string.isRequired,
  onSortChange: PropTypes.func.isRequired,

  // Filtering
  showViewedFilter: PropTypes.bool,
  isViewedFilter: PropTypes.oneOf([null, true, false]),
  onViewedFilterChange: PropTypes.func,

  // Actions
  onLoadMore: PropTypes.func.isRequired,
  onViewDocumentContent: PropTypes.func,

  // Utilities
  formatAmount: PropTypes.func.isRequired,

  // Customization
  emptyMessage: PropTypes.string,
  decisionKeyPrefix: PropTypes.string
};

export default DecisionListView;
