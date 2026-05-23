import React from 'react';

const ActivitySummary = ({ activityData, formatAmount }) => {
  if (!activityData || !activityData.data || activityData.data.length === 0) {
    return null;
  }

  return (
    <div className="activity-summary">
      <span className="summary-label">
        Activity by {activityData.granularity}s • Peak: {formatAmount(activityData.stats.max_amount)}
      </span>
      <span className="summary-periods">
        {activityData.stats.periods_with_activity} active periods
      </span>
    </div>
  );
};

export default ActivitySummary;
