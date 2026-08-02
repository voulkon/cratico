import React, { useState, useEffect, useRef } from 'react';
import { formatPrice } from '../utils/format';
import './ModelDropdown.css';

/**
 * Sortable model-dropdown component.
 *
 * Used in AISettingsPage for the model preference picker and inside the
 * KeyForm for per-key default model selection.  Provides sortable columns
 * (name, context length, prompt price, completion price) and a sticky header.
 */
const ModelDropdown = ({ models, value, onChange, disabled, placeholder, t }) => {
  const [open, setOpen] = useState(false);
  const [sortBy, setSortBy] = useState(null);
  const [sortDir, setSortDir] = useState('asc');
  const ref = useRef(null);

  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    if (open) {
      document.addEventListener('mousedown', handler);
      return () => document.removeEventListener('mousedown', handler);
    }
  }, [open]);

  const handleSort = (field) => {
    if (sortBy === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortBy(field);
      setSortDir('asc');
    }
  };

  const SortIndicator = ({ field }) => (
    <span className="ai-sort-indicator">
      <span
        className={`ai-sort-arrow ai-sort-arrow--up${sortBy === field && sortDir === 'asc' ? ' ai-sort-arrow--active' : ''}`}
      >
        ▲
      </span>
      <span
        className={`ai-sort-arrow ai-sort-arrow--down${sortBy === field && sortDir === 'desc' ? ' ai-sort-arrow--active' : ''}`}
      >
        ▼
      </span>
    </span>
  );

  const sorted = [...models].sort((a, b) => {
    const dir = sortDir === 'asc' ? 1 : -1;
    switch (sortBy) {
      case 'name':
        return dir * (a.name || a.id).localeCompare(b.name || b.id);
      case 'context':
        return dir * (a.context_length - b.context_length);
      case 'priceIn':
        return dir * (a.pricing.prompt - b.pricing.prompt);
      case 'priceOut':
        return dir * (a.pricing.completion - b.pricing.completion);
      default:
        return 0;
    }
  });

  const selected = models.find((m) => m.id === value);

  return (
    <div className="ai-model-dropdown" ref={ref}>
      <button
        className="ai-model-dropdown-trigger"
        onClick={() => setOpen((o) => !o)}
        disabled={disabled}
        type="button"
      >
        <span className="ai-model-dropdown-trigger-text">
          {selected
            ? `${selected.name || selected.id}  ·  ${t('aiSettings.ctx')} ${(selected.context_length / 1000).toFixed(0)}k  ·  $${formatPrice(selected.pricing.prompt, t)}/M ${t('aiSettings.in')}  ·  $${formatPrice(selected.pricing.completion, t)}/M ${t('aiSettings.out')}`
            : placeholder || t('aiSettings.usePipelineDefault')}
        </span>
        <span className="ai-model-dropdown-arrow">▾</span>
      </button>
      {open && (
        <div className="ai-model-dropdown-panel">
          <div className="ai-model-dropdown-header">
            <span
              className="ai-model-col ai-model-col--name ai-model-col--sortable"
              onClick={() => handleSort('name')}
            >
              {t('aiSettings.model')}<SortIndicator field="name" />
            </span>
            <span
              className="ai-model-col ai-model-col--context ai-model-col--sortable"
              onClick={() => handleSort('context')}
            >
              {t('aiSettings.ctx')}<SortIndicator field="context" />
            </span>
            <span
              className="ai-model-col ai-model-col--price ai-model-col--sortable"
              onClick={() => handleSort('priceIn')}
            >
              $/M {t('aiSettings.in')}<SortIndicator field="priceIn" />
            </span>
            <span
              className="ai-model-col ai-model-col--price ai-model-col--sortable"
              onClick={() => handleSort('priceOut')}
            >
              $/M {t('aiSettings.out')}<SortIndicator field="priceOut" />
            </span>
          </div>
          <div
            className={`ai-model-dropdown-option ${!value ? 'ai-model-dropdown-option--selected' : ''}`}
            onClick={() => { onChange(''); setOpen(false); }}
          >
            <span className="ai-model-col ai-model-col--name">{placeholder || t('aiSettings.usePipelineDefault')}</span>
            <span className="ai-model-col ai-model-col--context">—</span>
            <span className="ai-model-col ai-model-col--price">—</span>
            <span className="ai-model-col ai-model-col--price">—</span>
          </div>
          {sorted.map((m) => (
            <div
              key={m.id}
              className={`ai-model-dropdown-option ${m.id === value ? 'ai-model-dropdown-option--selected' : ''}`}
              onClick={() => { onChange(m.id); setOpen(false); }}
            >
              <span className="ai-model-col ai-model-col--name" title={m.name || m.id}>
                {m.name || m.id}
              </span>
              <span className="ai-model-col ai-model-col--context">
                {(m.context_length / 1000).toFixed(0)}k
              </span>
              <span className="ai-model-col ai-model-col--price">
                ${formatPrice(m.pricing.prompt, t)}
              </span>
              <span className="ai-model-col ai-model-col--price">
                ${formatPrice(m.pricing.completion, t)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default ModelDropdown;
