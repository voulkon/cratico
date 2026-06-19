import React from 'react';
import { useTranslation } from '../contexts/TranslationContext';
import { formatAmount } from '../utils/format';

/**
 * Shared stats footer for counterpart / relationship-pair cards.
 *
 * Displays total_amount and decision_count in the standard two-column layout.
 * Used by TopCounterparts and TopRelationshipPairs.
 */
const CounterpartStats = ({ totalAmount, decisionCount }) => {
  const { t } = useTranslation();

  return (
    <div className="counterpart-stats">
      <div className="stat-item">
        <span className="stat-label">{t('counterparts.totalAmount')}</span>
        <span className="stat-value amount">
          {formatAmount(totalAmount, { emptyText: t('common.noAmount') })}
        </span>
      </div>
      <div className="stat-item">
        <span className="stat-label">{t('counterparts.decisions')}</span>
        <span className="stat-value count">{decisionCount}</span>
      </div>
    </div>
  );
};

export default CounterpartStats;
