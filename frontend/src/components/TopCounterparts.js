import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import relationshipsApi from '../api/relationshipsApi';
import { useTranslation } from '../contexts/TranslationContext';
import './TopCounterparts.css';

/**
 * Reusable component to display top counterparts
 * For entities: shows top organizations
 * For organizations: shows top entities
 */
const TopCounterparts = ({
  type, // 'entity' or 'organization'
  id, // AFM for entity, UID for organization
  dateRange, // { start_date, end_date }
  limit = 5,
  onCounterpartClick // callback: (counterpart) => void - parent controls navigation URL
}) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    const fetchCounterparts = async () => {
      if (!id || !dateRange) {
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        setError(null);

        const params = {
          start_date: dateRange.start_date || dateRange.startDate,
          end_date: dateRange.end_date || dateRange.endDate,
          limit
        };

        let result;
        if (type === 'entity') {
          result = await relationshipsApi.getTopOrganizations(id, params);
        } else if (type === 'organization') {
          result = await relationshipsApi.getTopCounterparts(id, params);
        }

        setData(result);
      } catch (err) {
        console.error('Error fetching top counterparts:', err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchCounterparts();
  }, [id, type, dateRange, limit]);

  const formatAmount = (amount) => {
    if (!amount || amount === 0) return t('common.noAmount');
    return `€${amount.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    })}`;
  };

  const handleCounterpartClick = (counterpart) => {
    // Use parent-provided callback if available, otherwise fall back to prop-based URL
    if (onCounterpartClick) {
      onCounterpartClick(counterpart);
      return;
    }
    // Fallback: navigate using dateRange from props
    if (type === 'entity') {
      const orgUid = counterpart.decision__organization__uid;
      navigate(`/relationship/entity/${id}/org/${orgUid}?start_date=${dateRange.start_date}&end_date=${dateRange.end_date}`);
    } else if (type === 'organization') {
      const afm = counterpart.entity__afm;
      navigate(`/relationship/entity/${afm}/org/${id}?start_date=${dateRange.start_date}&end_date=${dateRange.end_date}`);
    }
  };

  if (loading) {
    return (
      <div className="top-counterparts-section">
        <h3 className="section-title">
          {type === 'entity' ? t('counterparts.topOrganizations') : t('counterparts.topEntities')}
        </h3>
        <div className="counterparts-loading">{t('common.loading')}...</div>
      </div>
    );
  }

  if (error || !data || !data.results || data.results.length === 0) {
    return null; // Don't show section if no data
  }

  const title = type === 'entity'
    ? t('counterparts.topOrganizations')
    : t('counterparts.topEntities');

  return (
    <div className="top-counterparts-section">
      <div className="section-header">
        <h3 className="section-title">{title}</h3>
        <button
          className="expand-toggle"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? t('common.collapse') : t('common.expand')} {expanded ? '▲' : '▼'}
        </button>
      </div>

      <div className="counterparts-info">
        <span className="date-range-info">
          {t('counterparts.dateRange')}: {new Date(data.date_range.start).toLocaleDateString()} - {new Date(data.date_range.end).toLocaleDateString()}
        </span>
        {data.pagination.total_count > limit && (
          <span className="total-count-info">
            {t('counterparts.showing')} {limit} {t('counterparts.of')} {data.pagination.total_count}
          </span>
        )}
      </div>

      <div className={`counterparts-grid ${expanded ? 'expanded' : 'collapsed'}`}>
        {data.results.map((counterpart, index) => {
          const name = type === 'entity'
            ? counterpart.decision__organization__label
            : counterpart.entity__name;
          const identifier = type === 'entity'
            ? counterpart.decision__organization__uid
            : counterpart.entity__afm;
          const entityType = type === 'organization' ? counterpart.entity__entity_type : null;

          return (
            <button
              key={index}
              className="counterpart-card"
              onClick={() => handleCounterpartClick(counterpart)}
            >
              <div className="counterpart-header">
                <span className="counterpart-rank">#{index + 1}</span>
                <span className="counterpart-name">{name}</span>
              </div>
              <div className="counterpart-details">
                <span className="counterpart-id">
                  {type === 'entity' ? 'UID' : 'AFM'}: {identifier}
                </span>
                {entityType && (
                  <span className="entity-type-badge">{t(`entityTypes.${entityType}`)}</span>
                )}
              </div>
              <div className="counterpart-stats">
                <div className="stat-item">
                  <span className="stat-label">{t('counterparts.totalAmount')}</span>
                  <span className="stat-value amount">{formatAmount(counterpart.total_amount)}</span>
                </div>
                <div className="stat-item">
                  <span className="stat-label">{t('counterparts.decisions')}</span>
                  <span className="stat-value count">{counterpart.decision_count}</span>
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {!expanded && data.results.length > 3 && (
        <button
          className="see-all-button"
          onClick={() => setExpanded(true)}
        >
          {t('counterparts.seeAll')} ({data.results.length})
        </button>
      )}
    </div>
  );
};

export default TopCounterparts;
