import React, { useState } from 'react';
import { useTranslation } from '../contexts/TranslationContext';
import './CompanyCapitalStocks.css';

const formatAmount = (amount, currency) => {
  
  if (amount == null) return '—';
  const currencySymbols = { Euro: '€', EUR: '€', USD: '$', GBP: '£' };
  const symbol = currencySymbols[currency] || currency || '€';
  return `${symbol}${parseFloat(amount).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
};

const CompanyCapitalStocks = ({ capital, stocks }) => {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(true);

  const hasCapital = capital && capital.length > 0;
  const hasStocks = stocks && stocks.length > 0;

  if (!hasCapital && !hasStocks) return null;

  return (
    <div className="company-capital-stocks">
      <button className="section-toggle" onClick={() => setIsOpen(!isOpen)}>
        <span className="section-toggle-label">{t('companyCapitalStocks.sectionTitle')}</span>
        <span className="toggle-arrow">{isOpen ? '▲' : '▼'}</span>
      </button>
      {isOpen && (<>

      {hasCapital && (
        <div className="capital-section">
          {capital.map((c, i) => (
            <div key={i} className="capital-grid">
              <div className="capital-item">
                <span className="info-label">{t('companyCapitalStocks.labelCapitalStock')}</span>
                <span className="capital-value">{formatAmount(c.capital_stock, c.currency)}</span>
              </div>
              {c.ecsokefalaiikes != null && c.ecsokefalaiikes !== 0 && (
                <div className="capital-item">
                  <span className="info-label">{t('companyCapitalStocks.labelExtraCapital')}</span>
                  <span className="capital-value">{formatAmount(c.ecsokefalaiikes, c.currency)}</span>
                </div>
              )}
              {c.eggiitikes != null && c.eggiitikes !== 0 && (
                <div className="capital-item">
                  <span className="info-label">{t('companyCapitalStocks.labelGuarantees')}</span>
                  <span className="capital-value">{formatAmount(c.eggiitikes, c.currency)}</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {hasStocks && (
        <div className="stocks-section">
          <div className="stocks-table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>{t('companyCapitalStocks.columnStockType')}</th>
                  <th>{t('companyCapitalStocks.columnAmount')}</th>
                  <th>{t('companyCapitalStocks.columnNominalValue')}</th>
                </tr>
              </thead>
              <tbody>
                {stocks.map((s, i) => (
                  <tr key={i}>
                    <td>{s.stock_type || '—'}</td>
                    <td className="stock-amount">
                      {s.amount != null ? parseFloat(s.amount).toLocaleString() : '—'}
                    </td>
                    <td className="stock-price">
                      {s.nominal_price != null
                        ? `€${parseFloat(s.nominal_price).toFixed(2)}`
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      </>)}
    </div>
  );
};

export default CompanyCapitalStocks;
