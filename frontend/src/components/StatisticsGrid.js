import React from 'react';
import './StatCard.css';
import './StatisticsGrid.css';

const StatisticsGrid = ({
  loading,
  error,
  cards,
  onRetry,
  columns = 4,
}) => {
  if (loading) {
    return (
      <div className="statistics-grid">
        {Array.from({ length: columns }).map((_, i) => (
          <div key={i} className="stat-card stat-card--loading">
            <div className="stat-skeleton stat-skeleton--title" />
            <div className="stat-skeleton stat-skeleton--value" />
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="statistics-grid">
        <div className="stat-card stat-card--error">
          <span>{error}</span>
          {onRetry && (
            <button className="retry-button" onClick={onRetry}>
              Retry
            </button>
          )}
        </div>
      </div>
    );
  }

  if (!cards) return null;

  return (
    <div className="statistics-grid">
      {cards.map((card, i) => (
        <div key={i} className="stat-card">
          <h3 className="stat-title">{card.title}</h3>
          <div className="stat-value">{card.value}</div>
          {card.subtitle && <div className="stat-context">{card.subtitle}</div>}
          {card.warning && <div className="discrepancy-warning">{card.warning}</div>}
        </div>
      ))}
    </div>
  );
};

export default StatisticsGrid;
