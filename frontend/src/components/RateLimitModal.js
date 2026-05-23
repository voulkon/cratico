import React, { useState, useEffect } from 'react';
import './RateLimitModal.css';

const RateLimitModal = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [errorInfo, setErrorInfo] = useState(null);

  useEffect(() => {
    const handleRateLimitExceeded = (event) => {
      setErrorInfo(event.detail);
      setIsOpen(true);
    };

    window.addEventListener('rateLimitExceeded', handleRateLimitExceeded);

    return () => {
      window.removeEventListener('rateLimitExceeded', handleRateLimitExceeded);
    };
  }, []);

  if (!isOpen) return null;

  const timeUntilReset = errorInfo?.resetTime ?
    Math.max(0, Math.ceil((errorInfo.resetTime - new Date()) / 1000 / 60)) : 0;

  return (
    <div className="rate-limit-modal-overlay">
      <div className="rate-limit-modal">
        <div className="modal-header">
          <h3>Rate Limit Exceeded</h3>
          <button
            className="close-button"
            onClick={() => setIsOpen(false)}
          >
            ×
          </button>
        </div>

        <div className="modal-body">
          <p>{errorInfo?.message}</p>

          {timeUntilReset > 0 && (
            <p>
              Your limit will reset in approximately {timeUntilReset} minutes.
            </p>
          )}

          <div className="modal-actions">
            <button
              className="btn btn-primary"
              onClick={() => window.location.href = '/pricing'}
            >
              Upgrade Subscription
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => setIsOpen(false)}
            >
              Continue
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default RateLimitModal;
