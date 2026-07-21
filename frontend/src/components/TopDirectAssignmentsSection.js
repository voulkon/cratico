import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import { useDateRange } from '../contexts/DateRangeContext';
import apiClient from '../api/client';
import { CollapsibleSection, DashboardSectionLoading } from './DashboardGrid';
import { formatCompactAmount } from '../utils/format';

const PAGE_SIZE = 5;

/**
 * TopDirectAssignmentsSection — Highest-amount direct-assignment decisions.
 *
 * Fetches from /decisions/top-direct-assignments/ with limit/offset.
 * Renders a simple ranked list — just the top 5.
 */
const TopDirectAssignmentsSection = ({
  onSeeAll,
  collapsible = false,
  className = '',
}) => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { dateRange } = useDateRange();

  const [decisions, setDecisions] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchDecisions = useCallback(async () => {
    if (!dateRange) return;

    try {
      setLoading(true);
      setError(null);

      const response = await apiClient.get(
        `/decisions/top-direct-assignments/?start_date=${dateRange.start_date}&end_date=${dateRange.end_date}&limit=${PAGE_SIZE}&offset=0`
      );

      setDecisions(response.data.results || []);
      setTotalCount(response.data.pagination?.total_count ?? 0);
    } catch (err) {
      console.error('Failed to load top direct assignments:', err);
      setError(err.response?.data?.error || err.message);
    } finally {
      setLoading(false);
    }
  }, [dateRange]);

  useEffect(() => {
    fetchDecisions();
  }, [fetchDecisions]);

  if (loading) {
    return <DashboardSectionLoading message={t('homepage.loading')} />;
  }

  if (error) {
    return (
      <CollapsibleSection
        title={t('homepage.highestDirectAssignments')}
        onSeeAll={onSeeAll}
        collapsible={collapsible}
        className={className}
      >
        <div className="dashboard-section-info">
          <span className="error-text">{error}</span>
        </div>
      </CollapsibleSection>
    );
  }

  return (
    <CollapsibleSection
      title={t('homepage.highestDirectAssignments')}
      onSeeAll={decisions.length > 0 ? onSeeAll : undefined}
      collapsible={collapsible}
      className={className}
    >
      <div className="dashboard-section-info">
        <span>{totalCount} {t('homepage.decisions')}</span>
      </div>
      <div className="dashboard-section-scroll">
        {decisions.length === 0 ? (
          <p className="dashboard-empty">{t('exploration.noResults')}</p>
        ) : (
          decisions.map((decision, index) => (
            <button
              key={decision.ada}
              className="dashboard-item-card"
              onClick={() => navigate(`/decision/${decision.id}`)}
            >
              <div className="dashboard-item-left">
                <span className="dashboard-rank">#{index + 1}</span>
              </div>
              <div className="dashboard-item-body">
                <div className="dashboard-item-title">
                  {decision.subject}
                </div>
                <div className="dashboard-item-subtitle">
                  {decision.organization?.label}
                </div>
              </div>
              <span className="dashboard-item-amount">{formatCompactAmount(decision.amount)}</span>
            </button>
          ))
        )}
      </div>
    </CollapsibleSection>
  );
};

export default TopDirectAssignmentsSection;
