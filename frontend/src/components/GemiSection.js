import React, { useState } from 'react';
import { useTranslation } from '../contexts/TranslationContext';
import CompanyInfoPanel from './CompanyInfoPanel';
import CompanyPersonsTable from './CompanyPersonsTable';
import CompanyActivitiesTable from './CompanyActivitiesTable';
import CompanyCapitalStocks from './CompanyCapitalStocks';
import './GemiSection.css';

const GemiSection = ({ companyInfo, entity, gemiFetchStatus, onRequestFetch }) => {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(true);

  const hasData = !!companyInfo;
  const neverAttempted = !entity.gemi_lookup_attempted;
  const attemptedButFailed = entity.gemi_lookup_attempted && !entity.gemi_lookup_success;

  return (
    <div className="gemi-section">
      <button
        type="button"
        className="gemi-section-header"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
      >
        <h2 className="gemi-section-title">{t('afmEntityDetail.gemiCompanyInformation')}</h2>
        <span className="gemi-section-toggle-arrow">{isOpen ? '▲' : '▼'}</span>
      </button>

      {isOpen && (
        <div className="gemi-section-body">
          {/* Case 1: Data available — persons first */}
          {hasData && (
            <div className="gemi-components-grid">
              <CompanyPersonsTable persons={companyInfo.persons} />
              <CompanyInfoPanel company={companyInfo} />
              <CompanyCapitalStocks capital={companyInfo.capital} stocks={companyInfo.stocks} />
              <CompanyActivitiesTable activities={companyInfo.activities} />
            </div>
          )}

          {/* Case 2: Never attempted — explain and offer the fetch button */}
          {!hasData && neverAttempted && (
            <div className="gemi-fetch-request">
              {(!gemiFetchStatus || gemiFetchStatus === 'error') && (
                <>
                  <p className="gemi-fetch-description">{t('afmEntityDetail.requestGemiFetchDescription')}</p>
                  <button
                    type="button"
                    className="gemi-fetch-button"
                    onClick={onRequestFetch}
                    disabled={gemiFetchStatus === 'loading'}
                  >
                    {t('afmEntityDetail.requestGemiFetch')}
                  </button>
                  {gemiFetchStatus === 'error' && (
                    <p className="gemi-fetch-message gemi-fetch-message--error">
                      {t('afmEntityDetail.requestGemiFetchError')}
                    </p>
                  )}
                </>
              )}
              {gemiFetchStatus === 'loading' && (
                <p className="gemi-fetch-message">{t('afmEntityDetail.requestGemiFetchPending')}</p>
              )}
              {gemiFetchStatus === 'queued' && (
                <p className="gemi-fetch-message gemi-fetch-message--success">
                  {t('afmEntityDetail.requestGemiFetchQueued')}
                </p>
              )}
              {gemiFetchStatus === 'already_queued' && (
                <p className="gemi-fetch-message gemi-fetch-message--info">
                  {t('afmEntityDetail.requestGemiFetchAlreadyQueued')}
                </p>
              )}
              {gemiFetchStatus === 'already_fetched' && (
                <p className="gemi-fetch-message gemi-fetch-message--info">
                  {t('afmEntityDetail.requestGemiFetchAlreadyFetched')}
                </p>
              )}
              {gemiFetchStatus === 'rate_limited' && (
                <p className="gemi-fetch-message gemi-fetch-message--warning">
                  {t('afmEntityDetail.requestGemiFetchRateLimited')}
                </p>
              )}
            </div>
          )}

          {/* Case 3: Attempted but GEMI returned no record */}
          {!hasData && attemptedButFailed && (
            <p className="gemi-fetch-message gemi-fetch-message--info">
              {t('afmEntityDetail.requestGemiFetchNotFound')}
            </p>
          )}
        </div>
      )}
    </div>
  );
};

export default GemiSection;
