import React from 'react';
import { useTranslation } from '../contexts/TranslationContext';

const SortControl = ({ sortBy, onSortChange, options = 'default' }) => {
  const { t } = useTranslation();

  // Define sort options based on the options parameter
  const sortOptions = options === 'default' ? [
    { value: 'recent', label: t('exploration.recent') },
    { value: 'oldest', label: t('exploration.oldest') },
    { value: 'amount_desc', label: t('exploration.amountDesc') },
    { value: 'amount_asc', label: t('exploration.amountAsc') }
  ] : options === 'simple' ? [
    { value: 'recent', label: t('entityDetail.mostRecent') },
    { value: 'amount_desc', label: t('entityDetail.highestAmountFirst') }
  ] : options;

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
