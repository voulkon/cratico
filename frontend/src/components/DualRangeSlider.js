import React, { useState, useRef, useCallback, useEffect } from 'react';
import SliderTooltip from './SliderTooltip';
import ActivityChart from './ActivityChart';
import ActivitySummary from './ActivitySummary';
import { useSliderFormatters } from '../hooks/useSliderFormatters';
import './DualRangeSlider.css';

const DualRangeSlider = ({
  min,
  max,
  startValue,
  endValue,
  onChange,
  label,
  formatValue,
  activityData = null
}) => {
  const [isDragging, setIsDragging] = useState(null);
  const [hoverValue, setHoverValue] = useState(null);
  const [hoverPosition, setHoverPosition] = useState({ x: 0, y: 0 });
  const [showActivityTooltip, setShowActivityTooltip] = useState(false);
  const [activityHoverData, setActivityHoverData] = useState(null);
  // Local state for drag values (only update parent on drag complete)
  const [localStartValue, setLocalStartValue] = useState(startValue);
  const [localEndValue, setLocalEndValue] = useState(endValue);
  const sliderRef = useRef(null);
  const { formatAmount, formatPeriod } = useSliderFormatters();

  // Update local values when props change (but not during drag)
  useEffect(() => {
    if (!isDragging) {
      setLocalStartValue(startValue);
      setLocalEndValue(endValue);
    }
  }, [startValue, endValue, isDragging]);

  const getValueFromPosition = useCallback((clientX) => {
    if (!sliderRef.current) return min;

    const rect = sliderRef.current.getBoundingClientRect();
    const percentage = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    return Math.round(min + percentage * (max - min));
  }, [min, max]);

  const getClientX = useCallback((e) => {
    return e.touches ? e.touches[0].clientX : e.clientX;
  }, []);

  const handleMouseDown = useCallback((type) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(type);
  }, []);

  const handleTouchStart = useCallback((type) => (e) => {
    e.stopPropagation();
    setIsDragging(type);
  }, []);
  const handleMouseMove = useCallback((e) => {
    if (!sliderRef.current) return;

    const clientX = getClientX(e);
    const rect = sliderRef.current.getBoundingClientRect();
    const percentage = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const value = Math.round(min + percentage * (max - min));

    // Always update hover value when not dragging
    if (!isDragging) {
      setHoverValue(value);
      setHoverPosition({ x: clientX, y: e.clientY || e.touches?.[0]?.clientY || 0 });

      // Handle activity data hover
      if (activityData && activityData.data) {
        const dataIndex = Math.floor(percentage * activityData.data.length);
        const hoveredDataPoint = activityData.data[Math.min(dataIndex, activityData.data.length - 1)];
        if (hoveredDataPoint) {
          setActivityHoverData(hoveredDataPoint);
          setShowActivityTooltip(true);
        }
      }
    }
  }, [isDragging, min, max, activityData, getClientX]);

  const handleTrackClick = useCallback((e) => {
    if (isDragging) return; // Don't handle track clicks while dragging
    if (e.touches) return; // Don't handle touch as click

    const clickValue = getValueFromPosition(getClientX(e));
    const startDistance = Math.abs(clickValue - localStartValue);
    const endDistance = Math.abs(clickValue - localEndValue);

    if (startDistance < endDistance) {
      const newEndValue = localEndValue;
      const newStartValue = Math.min(clickValue, newEndValue);
      setLocalStartValue(newStartValue);
      onChange(newStartValue, newEndValue);
    } else {
      const newStartValue = localStartValue;
      const newEndValue = Math.max(clickValue, newStartValue);
      setLocalEndValue(newEndValue);
      onChange(newStartValue, newEndValue);
    }
  }, [isDragging, getValueFromPosition, getClientX, localStartValue, localEndValue, onChange]);

  const handleTrackMouseLeave = useCallback(() => {
    if (!isDragging) {
      setHoverValue(null);
      setShowActivityTooltip(false);
      setActivityHoverData(null);
    }
  }, [isDragging]);

  // Keyboard navigation
  const handleKeyDown = useCallback((type) => (e) => {
    const step = e.shiftKey ? Math.ceil((max - min) / 10) : 1; // Shift for bigger steps

    switch (e.key) {
      case 'ArrowLeft':
      case 'ArrowDown':
        e.preventDefault();
        if (type === 'start') {
          const newValue = Math.max(min, localStartValue - step);
          setLocalStartValue(newValue);
          onChange(newValue, localEndValue);
        } else {
          const newValue = Math.max(localStartValue, localEndValue - step);
          setLocalEndValue(newValue);
          onChange(localStartValue, newValue);
        }
        break;
      case 'ArrowRight':
      case 'ArrowUp':
        e.preventDefault();
        if (type === 'start') {
          const newValue = Math.min(localEndValue, localStartValue + step);
          setLocalStartValue(newValue);
          onChange(newValue, localEndValue);
        } else {
          const newValue = Math.min(max, localEndValue + step);
          setLocalEndValue(newValue);
          onChange(localStartValue, newValue);
        }
        break;
      case 'Home':
        e.preventDefault();
        if (type === 'start') {
          setLocalStartValue(min);
          onChange(min, localEndValue);
        } else {
          setLocalEndValue(localStartValue);
          onChange(localStartValue, localStartValue);
        }
        break;
      case 'End':
        e.preventDefault();
        if (type === 'start') {
          setLocalStartValue(localEndValue);
          onChange(localEndValue, localEndValue);
        } else {
          setLocalEndValue(max);
          onChange(localStartValue, max);
        }
        break;
      case 'PageUp':
        e.preventDefault();
        {
          const bigStep = Math.ceil((max - min) / 5);
          if (type === 'start') {
            const newValue = Math.min(localEndValue, localStartValue + bigStep);
            setLocalStartValue(newValue);
            onChange(newValue, localEndValue);
          } else {
            const newValue = Math.min(max, localEndValue + bigStep);
            setLocalEndValue(newValue);
            onChange(localStartValue, newValue);
          }
        }
        break;
      case 'PageDown':
        e.preventDefault();
        {
          const bigStep = Math.ceil((max - min) / 5);
          if (type === 'start') {
            const newValue = Math.max(min, localStartValue - bigStep);
            setLocalStartValue(newValue);
            onChange(newValue, localEndValue);
          } else {
            const newValue = Math.max(localStartValue, localEndValue - bigStep);
            setLocalEndValue(newValue);
            onChange(localStartValue, newValue);
          }
        }
        break;
      default:
        break;
    }
  }, [min, max, localStartValue, localEndValue, onChange]);

  // Global mouse event handlers for dragging
  useEffect(() => {
    if (isDragging) {
      const handleGlobalMouseMove = (e) => {
        if (!sliderRef.current) return;

        const clientX = getClientX(e);
        const rect = sliderRef.current.getBoundingClientRect();
        const percentage = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
        const value = Math.round(min + percentage * (max - min));

        // Update local state during drag (don't call onChange yet)
        if (isDragging === 'start') {
          const newStartValue = Math.min(value, localEndValue);
          setLocalStartValue(newStartValue);
        } else if (isDragging === 'end') {
          const newEndValue = Math.max(value, localStartValue);
          setLocalEndValue(newEndValue);
        }
      };

      const handleGlobalMouseUp = () => {
        // Call onChange only when drag completes
        onChange(localStartValue, localEndValue);
        setIsDragging(null);
      };

      // Add both mouse and touch event listeners
      document.addEventListener('mousemove', handleGlobalMouseMove, { passive: false });
      document.addEventListener('mouseup', handleGlobalMouseUp);
      document.addEventListener('touchmove', handleGlobalMouseMove, { passive: false });
      document.addEventListener('touchend', handleGlobalMouseUp);
      document.addEventListener('touchcancel', handleGlobalMouseUp);
      document.body.style.userSelect = 'none';
      document.body.style.cursor = 'grabbing';

      return () => {
        document.removeEventListener('mousemove', handleGlobalMouseMove);
        document.removeEventListener('mouseup', handleGlobalMouseUp);
        document.removeEventListener('touchmove', handleGlobalMouseMove);
        document.removeEventListener('touchend', handleGlobalMouseUp);
        document.removeEventListener('touchcancel', handleGlobalMouseUp);
        document.body.style.userSelect = '';
        document.body.style.cursor = '';
      };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDragging, min, max, localStartValue, localEndValue, onChange, getClientX]);

  // Use local values for rendering during drag, prop values otherwise
  const displayStartValue = isDragging ? localStartValue : startValue;
  const displayEndValue = isDragging ? localEndValue : endValue;

  const startPercentage = Math.max(0, Math.min(100, ((displayStartValue - min) / (max - min)) * 100));
  const endPercentage = Math.max(0, Math.min(100, ((displayEndValue - min) / (max - min)) * 100));

  const startLabel = formatValue(displayStartValue);
  const endLabel = formatValue(displayEndValue);

  const isOverlapping = displayStartValue === displayEndValue;
  const handleStyle = (percentage) => ({
    left: `${percentage}%`,
    ...(isOverlapping ? { '--handle-position': `${percentage}%` } : {}),
  });

  return (
    <div className="dual-range-slider">
      <div className="slider-header">
        <label className="slider-label">{label}:</label>
        <div className="slider-values">
          <span className="value-badge">{startLabel}</span>
          <span className="value-separator">to</span>
          <span className="value-badge">{endLabel}</span>
        </div>
      </div>

      <div className="slider-container">
        <div
          ref={sliderRef}
          className="slider-track"
          onClick={handleTrackClick}
          onMouseMove={handleMouseMove}
          onTouchMove={handleMouseMove}
          onMouseLeave={handleTrackMouseLeave}
          onTouchEnd={handleTrackMouseLeave}
        >
          <ActivityChart activityData={activityData} />
        </div>

        <div
          className="slider-range"
          style={{
            left: `${startPercentage}%`,
            width: `${endPercentage - startPercentage}%`,
          }}
        />

        <div
          className={`slider-handle start${isDragging === 'start' ? ' dragging' : ''}${isOverlapping ? ' overlap start' : ''}`}
          style={handleStyle(startPercentage)}
          onMouseDown={handleMouseDown('start')}
          onTouchStart={handleTouchStart('start')}
          onKeyDown={handleKeyDown('start')}
          tabIndex={0}
          role="slider"
          aria-label="Start value"
          aria-valuemin={min}
          aria-valuemax={displayEndValue}
          aria-valuenow={displayStartValue}
          aria-valuetext={startLabel}
        />
        <div
          className={`slider-handle end${isDragging === 'end' ? ' dragging' : ''}${isOverlapping ? ' overlap end' : ''}`}
          style={handleStyle(endPercentage)}
          onMouseDown={handleMouseDown('end')}
          onTouchStart={handleTouchStart('end')}
          onKeyDown={handleKeyDown('end')}
          tabIndex={0}
          role="slider"
          aria-label="End value"
          aria-valuemin={displayStartValue}
          aria-valuemax={max}
          aria-valuenow={displayEndValue}
          aria-valuetext={endLabel}
        />

        <SliderTooltip
          isVisible={(hoverValue !== null || showActivityTooltip) && !isDragging}
          position={hoverPosition}
          hoverValue={hoverValue}
          activityHoverData={activityHoverData}
          activityGranularity={activityData?.granularity}
          formatValue={formatValue}
          formatAmount={formatAmount}
          formatPeriod={formatPeriod}
        />

        {isDragging && (
          <div
            className="drag-feedback-tooltip"
            style={{ left: `${isDragging === 'start' ? startPercentage : endPercentage}%` }}
          >
            {isDragging === 'start' ? startLabel : endLabel}
          </div>
        )}
      </div>

      <ActivitySummary activityData={activityData} formatAmount={formatAmount} />
    </div>
  );
};

export default DualRangeSlider;
