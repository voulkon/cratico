import React, { useCallback } from 'react';
import DualRangeSlider from './DualRangeSlider';
import { useTranslation } from '../contexts/TranslationContext';
import CollapsibleCard from './CollapsibleCard';
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

  const formatSliderValue = useCallback(
    (value) => {
      if (!dynamicDateUtils) return '';
      return dynamicDateUtils.formatMonth(value);
    },
    [dynamicDateUtils],
  );

  const hasDateRange = dateRange && dateRange.span_days != null;

  return (
    <CollapsibleCard
      title={t('exploration.timeRange')}
      open={controlledOpen}
      onToggle={onToggle}
      defaultOpen={defaultOpen}
      className="time-range-container"
    >
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
    </CollapsibleCard>
  );
};

export default TimeRangeSection;
