import React from 'react';

const SliderTooltip = ({
  isVisible,
  position,
  hoverValue,
  activityHoverData,
  activityGranularity,
  formatValue,
  formatAmount,
  formatPeriod
}) => {
  if (!isVisible) return null;

  return (
    <div
      className="slider-tooltip enhanced"
      style={{
        left: position.x + 10,
        top: position.y - 80,
      }}
    >
      <div className="tooltip-time">{formatValue(hoverValue)}</div>
      {activityHoverData && (
        <div className="tooltip-activity">
          <div className="activity-period">
            {formatPeriod(activityHoverData.period, activityGranularity)}
          </div>
          <div className="activity-stats">
            <span className="activity-count">{activityHoverData.count} decisions</span>
            <span className="activity-amount">{formatAmount(activityHoverData.amount)}</span>
          </div>
        </div>
      )}
    </div>
  );
};

export default SliderTooltip;
