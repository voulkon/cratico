import React, { useState, useEffect } from 'react';
import './RateLimitIndicator.css';

const RateLimitIndicator = () => {
  const [rateLimitInfo, setRateLimitInfo] = useState(null);
  const [showWarning, setShowWarning] = useState(false);

  useEffect(() => {
    // Load initial rate limit info
    const stored = localStorage.getItem('rateLimitInfo');
    if (stored) {
      setRateLimitInfo(JSON.parse(stored));
    }

    // Listen for rate limit updates
    const handleRateLimitUpdate = (event) => {
      setRateLimitInfo(event.detail);

      // Show warning if getting close to limit
      const remaining = event.detail.remaining;
      const limit = event.detail.limit;
      const percentage = (remaining / limit) * 100;

      setShowWarning(percentage <= 20); // Show warning at 20% remaining
    };

    window.addEventListener('rateLimitUpdate', handleRateLimitUpdate);

    return () => {
      window.removeEventListener('rateLimitUpdate', handleRateLimitUpdate);
    };
  }, []);

  if (!rateLimitInfo) return null;

  const percentage = (rateLimitInfo.remaining / rateLimitInfo.limit) * 100;
  const resetTime = new Date(rateLimitInfo.reset * 1000);

  return (
    <div className={`rate-limit-indicator ${showWarning ? 'warning' : ''}`}>
      <div className="rate-limit-bar">
        <div
          className="rate-limit-fill"
          style={{ width: `${100 - percentage}%` }}
        />
      </div>
      <div className="rate-limit-text">
        API Requests: {rateLimitInfo.limit - rateLimitInfo.remaining}/{rateLimitInfo.limit}
        {showWarning && (
          <span className="warning-text">
            ({rateLimitInfo.remaining} remaining)
          </span>
        )}
      </div>
      <div className="rate-limit-reset">
        Resets: {resetTime.toLocaleTimeString()}
      </div>
    </div>
  );
};

export default RateLimitIndicator;
