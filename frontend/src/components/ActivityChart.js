import React from 'react';
import { useTheme } from '../contexts/ThemeContext';

const ActivityChart = ({ activityData }) => {
  const { getCurrentPaletteColor } = useTheme();

  if (!activityData || !activityData.data || activityData.data.length === 0) {
    return null;
  }

  const generateActivityPath = () => {
    const data = activityData.data;
    const maxAmount = activityData.stats.max_amount;
    const trackHeight = 8;
    const chartHeight = 20;

    if (maxAmount === 0) return '';

    const points = data.map((item, index) => {
      const x = (index / (data.length - 1)) * 100;
      const y = trackHeight + (item.amount / maxAmount) * chartHeight;
      return `${x},${y}`;
    }).join(' ');

    return `M 0,${trackHeight} L ${points} L 100,${trackHeight} Z`;
  };

  const themeColor = getCurrentPaletteColor();
  const gradientId = `activityGradient-${Math.random().toString(36).substr(2, 9)}`;

  return (
    <svg
      className="activity-background"
      viewBox="0 0 100 32"
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id={gradientId} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={themeColor} stopOpacity="0.3"/>
          <stop offset="100%" stopColor={themeColor} stopOpacity="0.1"/>
        </linearGradient>
      </defs>
      <path
        d={generateActivityPath()}
        fill={`url(#${gradientId})`}
        stroke={themeColor}
        strokeWidth="0.5"
        strokeOpacity="0.4"
      />
    </svg>
  );
};

export default ActivityChart;
