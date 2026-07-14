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
      <span className="stat-value amount">
        {formatAmount(totalAmount, { emptyText: t('common.noAmount') })}
      </span>
      <span className="stat-subtitle">
        {t('counterparts.decisionsCount', { count: decisionCount })}
      </span>
    </div>
  );
};

export default CounterpartStats;
