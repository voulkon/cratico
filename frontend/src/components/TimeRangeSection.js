import React, { useCallback, useState } from 'react';
import DualRangeSlider from './DualRangeSlider';
import { useTranslation } from '../contexts/TranslationContext';
import './TimeRangeSection.css';

/**
 * TimeRangeSection — a collapsible time-range slider with activity chart.
 *
 * Used across EntityDetailPage, AFMEntityDetailPage, and RelationshipDetailPage
 * to eliminate duplicated <details>/<DualRangeSlider> boilerplate.
 *
 * Props:
 *   dynamicDateUtils     – from createDynamicDateRangeUtils(dateRangeResponse)
 *   monthRange           – { startIndex, endIndex }
 *   onMonthRangeChange   – (startIndex, endIndex) => void
 *   dateRange            – { earliest, latest, span_days }  (optional; if omitted
 *                           summary-count and date-span-info are hidden)
 *   activityData         – activity_chart from the date-range API
 *   summaryPrefix        – optional prefix before the day count
 *                           e.g. t('exploration.entityData')
 *   showDateSpanInfo     – whether to show "available: X to Y (N days)"
 *   open                 – controlled open state (pass with onToggle)
 *   onToggle             – controlled toggle handler
 *   defaultOpen          – initial open state when uncontrolled (default: true)
 */
const TimeRangeSection = ({
  dynamicDateUtils,
  monthRange,
  onMonthRangeChange,
  dateRange,
  activityData,
  summaryPrefix = null,
  showDateSpanInfo = false,
  open: controlledOpen,
  onToggle,
  defaultOpen = true,
}) => {
  const { t } = useTranslation();
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);

  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? controlledOpen : uncontrolledOpen;

  const handleToggle = (e) => {
    if (isControlled) {
      onToggle?.(e.target.open);
    } else {
      setUncontrolledOpen(e.target.open);
    }
  };

  const formatSliderValue = useCallback(
    (value) => {
      if (!dynamicDateUtils) return '';
      return dynamicDateUtils.formatMonth(value);
    },
    [dynamicDateUtils],
  );

  const hasDateRange = dateRange && dateRange.span_days != null;

  return (
    <details
      className="time-range-container collapsible-section"
      open={isOpen}
      onToggle={handleToggle}
    >
      <summary className="section-summary">
        <span className="summary-title">{t('exploration.timeRange')}</span>
        <svg
          className={`chevron${isOpen ? ' open' : ''}`}
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M4 6l4 4 4-4" />
        </svg>
      </summary>

      <div className="section-content">
        {showDateSpanInfo && hasDateRange && (
          <div className="time-range-header">
            <span className="date-span-info">
              {t('exploration.availableData', {
                start: dateRange.earliest,
                end: dateRange.latest,
                days: dateRange.span_days,
              })}
            </span>
          </div>
        )}

        <DualRangeSlider
          min={0}
          max={dynamicDateUtils.totalMonths - 1}
          startValue={monthRange.startIndex}
          endValue={monthRange.endIndex}
          onChange={onMonthRangeChange}
          label={t('entityDetail.selectTimePeriod')}
          formatValue={formatSliderValue}
          activityData={activityData}
        />

        {hasDateRange && (
          <div className="summary-count-row">
            <span className="summary-count">
              {summaryPrefix && <>{summaryPrefix} — </>}
              {t('exploration.availableDataShort', {
                days: dateRange.span_days,
              })}
            </span>
          </div>
        )}
      </div>
    </details>
  );
};

export default TimeRangeSection;
