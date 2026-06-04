import React, { useState, useEffect } from 'react';
import './SearchInput.css';

const SearchInput = ({
  value,
  onChange,
  placeholder,
  debounceMs = 500,
  label,
  className,
}) => {
  const [localValue, setLocalValue] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => onChange(localValue), debounceMs);
    return () => clearTimeout(timer);
  }, [localValue, debounceMs]); // eslint-disable-line react-hooks/exhaustive-deps

  // Sync external value changes back to local state
  useEffect(() => {
    setLocalValue(value);
  }, [value]);

  return (
    <div className={`search-container${className ? ` ${className}` : ''}`}>
      {label && <label className="search-label">{label}</label>}
      <div className="search-input-wrapper">
        <input
          type="text"
          value={localValue}
          onChange={(e) => setLocalValue(e.target.value)}
          placeholder={placeholder}
          className="search-input"
        />
        {localValue && (
          <button
            onClick={() => {
              setLocalValue('');
              onChange('');
            }}
            className="clear-button"
          >
            ×
          </button>
        )}
      </div>
    </div>
  );
};

export default SearchInput;
