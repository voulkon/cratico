import React, { useEffect, useState } from 'react';
import './RateLimitIndicator.css';

const RATE_LIMIT_TTL_MS = 10 * 60 * 1000;

const parseStoredRateLimit = () => {
  try {
    const raw = localStorage.getItem('rateLimitInfo');
    if (!raw) return null;

    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed.remaining !== 'number' || typeof parsed.limit !== 'number') {
      return null;
    }

    return parsed;
  } catch (error) {
    return null;
  }
};

const isFresh = (value) => {
  if (!value) return false;
  const updatedAt = value.updatedAt || Date.now();
  return Date.now() - updatedAt < RATE_LIMIT_TTL_MS;
};

const RateLimitIndicator = ({ label }) => {
  const [rateLimitInfo, setRateLimitInfo] = useState(() => parseStoredRateLimit());

  useEffect(() => {
    const syncFromStorage = () => {
      const info = parseStoredRateLimit();
      setRateLimitInfo(isFresh(info) ? info : null);
    };

    const handleRateLimitUpdate = (event) => {
      const detail = event.detail || {};
      const nextInfo = {
        ...detail,
        updatedAt: detail.updatedAt || Date.now(),
      };

      if (typeof nextInfo.remaining !== 'number' || typeof nextInfo.limit !== 'number') {
        setRateLimitInfo(null);
        return;
      }

      localStorage.setItem('rateLimitInfo', JSON.stringify(nextInfo));
      setRateLimitInfo(isFresh(nextInfo) ? nextInfo : null);
    };

    syncFromStorage();
    window.addEventListener('rateLimitUpdate', handleRateLimitUpdate);

    return () => {
      window.removeEventListener('rateLimitUpdate', handleRateLimitUpdate);
    };
  }, []);

  if (!rateLimitInfo) {
    return null;
  }

  const { remaining, limit } = rateLimitInfo;
  const percentRemaining = limit > 0
    ? Math.min(100, Math.max(0, (remaining / limit) * 100))
    : 0;

  // Tone the bar by how much quota is left: healthy → palette accent,
  // low → warning, nearly exhausted → danger.
  let meterColor = 'var(--palette-primary)';
  if (percentRemaining <= 5) {
    meterColor = 'var(--danger-color)';
  } else if (percentRemaining <= 20) {
    meterColor = 'var(--warning-color)';
  }

  return (
    <>
      <div className="menu-divider"></div>
      <div className="menu-section">
        <div className="rate-limit-row" data-testid="rate-limit-indicator">
          <div className="rate-limit-row-header">
            <span className="rate-limit-row-label">{label}</span>
            <span className="rate-limit-row-value">
              {remaining} / {limit}
            </span>
          </div>
          <div className="rate-limit-meter" aria-hidden="true">
            <span
              className="rate-limit-meter-fill"
              style={{ width: `${percentRemaining}%`, backgroundColor: meterColor }}
            />
          </div>
        </div>
      </div>
    </>
  );
};

export default RateLimitIndicator;
