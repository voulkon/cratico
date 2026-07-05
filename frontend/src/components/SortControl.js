import React from 'react';
import { useTranslation } from '../contexts/TranslationContext';

const SortControl = ({ sortBy, onSortChange, options = 'simple' }) => {
  const { t } = useTranslation();

  // Define sort options based on the options parameter.
  // 'simple' (default) → 2 options (recent + amount_desc)
  // 'full'              → 4 options (recent, oldest, amount_desc, amount_asc)
  // array              → used as-is
  const sortOptions = options === 'full' ? [
    { value: 'recent', label: t('exploration.recent') },
    { value: 'oldest', label: t('exploration.oldest') },
    { value: 'amount_desc', label: t('exploration.amountDesc') },
    { value: 'amount_asc', label: t('exploration.amountAsc') }
  ] : (Array.isArray(options) ? options : [
    { value: 'recent', label: t('entityDetail.mostRecent') },
    { value: 'amount_desc', label: t('entityDetail.highestAmountFirst') }
  ]);

  return (
    <div className="sort-container">
      <label className="sort-label">{t('exploration.sortBy')}:</label>
      <select
        value={sortBy}
        onChange={(e) => onSortChange(e.target.value)}
        className="sort-select"
      >
        {sortOptions.map(option => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
};

export default SortControl;
