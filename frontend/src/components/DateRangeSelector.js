import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDateRange } from '../contexts/DateRangeContext';
import { useTranslation } from '../contexts/TranslationContext';
import { CalendarIcon, CheckIcon, XIcon, AlertIcon, PencilIcon, SearchIcon } from './Icons';
import './DateRangeSelector.css';

const DateRangeSelector = ({ className = '' }) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { period, setPeriod, dateRange, setCustomRange } = useDateRange();
  const [isEditing, setIsEditing] = useState(false);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [displayStartDate, setDisplayStartDate] = useState('');
  const [displayEndDate, setDisplayEndDate] = useState('');
  const [validationError, setValidationError] = useState('');
  const startInputRef = useRef(null);
  const endInputRef = useRef(null);

  // Format date to DD/MM/YYYY for display
  const formatDateForDisplay = (dateString) => {
    if (!dateString) return '';
    const date = new Date(dateString);
    if (isNaN(date.getTime())) return '';
    const day = date.getDate().toString().padStart(2, '0');
    const month = (date.getMonth() + 1).toString().padStart(2, '0');
    const year = date.getFullYear();
    return `${day}/${month}/${year}`;
  };

  // Convert DD/MM/YYYY to YYYY-MM-DD
  const parseDisplayDate = (displayDate) => {
    if (!displayDate) return '';
    const parts = displayDate.split('/');
    if (parts.length === 3) {
      const day = parts[0].padStart(2, '0');
      const month = parts[1].padStart(2, '0');
      const year = parts[2];
      if (year.length === 4 && !isNaN(parseInt(day)) && !isNaN(parseInt(month))) {
        return `${year}-${month}-${day}`;
      }
    }
    return '';
  };

  // Validate date format DD/MM/YYYY
  const isValidDisplayFormat = (displayDate) => {
    const regex = /^\d{1,2}\/\d{1,2}\/\d{4}$/;
    if (!regex.test(displayDate)) return false;
    const parts = displayDate.split('/');
    const day = parseInt(parts[0]);
    const month = parseInt(parts[1]);
    const year = parseInt(parts[2]);
    const date = new Date(year, month - 1, day);
    return date.getFullYear() === year &&
           date.getMonth() === month - 1 &&
           date.getDate() === day;
  };

  // Update local state when dateRange changes
  useEffect(() => {
    if (dateRange) {
      setStartDate(dateRange.start_date);
      setEndDate(dateRange.end_date);
      setDisplayStartDate(formatDateForDisplay(dateRange.start_date));
      setDisplayEndDate(formatDateForDisplay(dateRange.end_date));
    }
  }, [dateRange]);

  const handleDisplayChange = (type, value) => {
    // Only allow numbers and slashes
    const cleaned = value.replace(/[^\d/]/g, '');

    if (type === 'start') {
      setDisplayStartDate(cleaned);
      setValidationError('');
      // Try to parse if it looks complete
      if (isValidDisplayFormat(cleaned)) {
        const isoDate = parseDisplayDate(cleaned);
        setStartDate(isoDate);
      }
    } else {
      setDisplayEndDate(cleaned);
      setValidationError('');
      if (isValidDisplayFormat(cleaned)) {
        const isoDate = parseDisplayDate(cleaned);
        setEndDate(isoDate);
      }
    }
  };

  const handleNativeDateChange = (type, value) => {
    if (type === 'start') {
      setStartDate(value);
      setDisplayStartDate(formatDateForDisplay(value));
    } else {
      setEndDate(value);
      setDisplayEndDate(formatDateForDisplay(value));
    }
    setValidationError('');
  };

  const validateDateRange = () => {
    if (!startDate || !endDate) {
      setValidationError(t('dateRange.bothDatesRequired') || 'Both dates are required');
      return false;
    }

    const start = new Date(startDate);
    const end = new Date(endDate);

    if (isNaN(start.getTime()) || isNaN(end.getTime())) {
      setValidationError(t('dateRange.invalidDate') || 'Please enter valid dates');
      return false;
    }

    if (end < start) {
      setValidationError(t('dateRange.endBeforeStart') || 'End date cannot be before start date');
      return false;
    }

    return true;
  };

  const applyCustomRange = () => {
    if (!validateDateRange()) {
      return;
    }

    setCustomRange({
      start_date: startDate,
      end_date: endDate
    });
    setPeriod('custom');
    setIsEditing(false);
    setValidationError('');
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') {
      applyCustomRange();
    } else if (e.key === 'Escape') {
      setIsEditing(false);
      setValidationError('');
      if (dateRange) {
        setStartDate(dateRange.start_date);
        setEndDate(dateRange.end_date);
        setDisplayStartDate(formatDateForDisplay(dateRange.start_date));
        setDisplayEndDate(formatDateForDisplay(dateRange.end_date));
      }
    }
  };

  const periods = [
    { value: 'yesterday', label: t('dateRange.yesterday') || 'Yesterday' },
    { value: 'week', label: t('dateRange.week') || 'Week' },
    { value: 'month', label: t('dateRange.month') || 'Month' },
    { value: 'year', label: t('dateRange.year') || 'Year' },
    { value: 'custom', label: t('dateRange.custom') || 'Custom' }
  ];

  const handleExploreClick = () => {
    if (dateRange) {
      navigate(`/explore/temporal/${dateRange.start_date}/${dateRange.end_date}`);
    }
  };

  return (
    <div className={`date-range-selector ${className}`}>
      <div className="period-controls">
        <div className="period-buttons">
          {periods.map(({ value, label }) => (
            <button
              key={value}
              className={`period-button ${period === value ? 'active' : ''}`}
              onClick={() => {
                setPeriod(value);
                if (value === 'custom') {
                  setIsEditing(true);
                }
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          className="explore-button"
          onClick={handleExploreClick}
          disabled={!dateRange}
          title={t('dateRange.exploreInDetail') || 'Explore this period in detail'}
        >
          <SearchIcon size={16} />
          <span>{t('dateRange.explore') || 'Explore'}</span>
        </button>
      </div>
      {dateRange && (
        <div className={`date-range-display ${period === 'custom' ? 'custom-range' : ''}`}>
          {isEditing || period === 'custom' ? (
            <div className="date-inputs-wrapper">
              <div className="date-inputs">
                <div className="date-input-container">
                  <input
                    type="text"
                    value={displayStartDate}
                    onChange={(e) => handleDisplayChange('start', e.target.value)}
                    onKeyDown={handleKeyPress}
                    className={`date-input ${validationError ? 'error' : ''}`}
                    placeholder="DD/MM/YYYY"
                    maxLength={10}
                  />
                  <input
                    ref={startInputRef}
                    type="date"
                    value={startDate}
                    onChange={(e) => handleNativeDateChange('start', e.target.value)}
                    className="date-picker-hidden"
                    tabIndex={-1}
                  />
                  <button
                    className="calendar-button"
                    onClick={() => startInputRef.current?.showPicker?.() || startInputRef.current?.click()}
                    title={t('dateRange.openCalendar') || 'Open calendar'}
                    type="button"
                  >
                    <CalendarIcon size={16} />
                  </button>
                </div>
                <span className="date-separator">-</span>
                <div className="date-input-container">
                  <input
                    type="text"
                    value={displayEndDate}
                    onChange={(e) => handleDisplayChange('end', e.target.value)}
                    onKeyDown={handleKeyPress}
                    className={`date-input ${validationError ? 'error' : ''}`}
                    placeholder="DD/MM/YYYY"
                    maxLength={10}
                  />
                  <input
                    ref={endInputRef}
                    type="date"
                    value={endDate}
                    onChange={(e) => handleNativeDateChange('end', e.target.value)}
                    className="date-picker-hidden"
                    tabIndex={-1}
                  />
                  <button
                    className="calendar-button"
                    onClick={() => endInputRef.current?.showPicker?.() || endInputRef.current?.click()}
                    title={t('dateRange.openCalendar') || 'Open calendar'}
                    type="button"
                  >
                    <CalendarIcon size={16} />
                  </button>
                </div>
                <button
                  onClick={applyCustomRange}
                  className="apply-button"
                  title={t('dateRange.apply') || 'Apply'}
                  type="button"
                >
                  <CheckIcon size={16} />
                </button>
                {period === 'custom' && (
                  <button
                    onClick={() => {
                      setIsEditing(false);
                      setValidationError('');
                    }}
                    className="cancel-button"
                    title={t('dateRange.cancel') || 'Cancel'}
                    type="button"
                  >
                    <XIcon size={16} />
                  </button>
                )}
              </div>
              {validationError && (
                <div className="validation-error">
                  <AlertIcon size={14} className="validation-error-icon" />
                  {validationError}
                </div>
              )}
            </div>
          ) : (
            <div className="date-display" onClick={() => setIsEditing(true)}>
              {formatDateForDisplay(dateRange.start_date)} - {formatDateForDisplay(dateRange.end_date)}
              <PencilIcon size={14} className="edit-hint" title={t('dateRange.clickToEdit') || 'Click to edit'} />
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default DateRangeSelector;
