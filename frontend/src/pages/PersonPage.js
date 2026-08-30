import React, { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import apiClient from '../api/client';
import { useTranslation } from '../contexts/TranslationContext';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { SearchIcon } from '../components/Icons';
import TopBarSlot from '../components/TopBarSlot';
import './PersonPage.css';

const PersonPage = () => {
  const { t } = useTranslation();
  const { personName } = useParams();
  const navigate = useNavigate();
  const decodedName = decodeURIComponent(personName);
  useDocumentTitle(decodedName);

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    apiClient.get(`/companies/persons/${encodeURIComponent(decodedName)}/`)
      .then(res => setData(res.data))
      .catch(err => setError(err.response?.data?.error || err.message))
      .finally(() => setLoading(false));
  }, [decodedName]);

  if (loading) {
    return (
      <div className="person-page">
        <div className="loading-container">
          <div className="spinner"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="person-page">
        <div className="error-container">
          <h2>{t('personPage.errorTitle')}</h2>
          <p>{error}</p>
          <button onClick={() => navigate(-1)} className="breadcrumb-link">← {t('personPage.backButton')}</button>
        </div>
      </div>
    );
  }

  const { involvements } = data;

  return (
    <div className="person-page">
      {/* Person name rendered into the fixed top bar */}
      <TopBarSlot>
        <div className="person-header-topbar">
          <span className="person-title-topbar">{decodedName}</span>
        </div>
      </TopBarSlot>

      <div className="person-page-header">
        <div className="breadcrumb">
          <button onClick={() => navigate(-1)} className="breadcrumb-link">← {t('personPage.backButton')}</button>
          <span className="breadcrumb-separator">•</span>
          <span>{t('personPage.breadcrumbPerson')}</span>
        </div>
        <div className="person-title-row">
          <a
            href={`https://www.google.com/search?q=${encodeURIComponent(decodedName)}`}
            target="_blank"
            rel="noopener noreferrer"
            className="person-google-search"
            title={t('personPage.searchOnGoogle')}
          >
            <SearchIcon size={16} />
            <span className="google-search-label">{t('personPage.searchOnGoogle')}</span>
          </a>
        </div>
        <p className="person-subtitle">
          {t('personPage.involvements', { count: involvements.length })}
        </p>
      </div>

      <div className="person-companies-list">
        {involvements.map((inv, i) => {
          const c = inv.company;
          const isActive = c.status_name === 'Ενεργή';
          return (
            <div key={i} className="person-company-card">
              <div>
                <Link
                  to={`/entity/afm/${c.afm}`}
                  className="person-company-name"
                >
                  {c.co_name_el || c.co_names_en?.[0] || '—'}
                </Link>
                <div className="person-company-meta">
                  {c.status_name && (
                    <span className={`company-status-badge ${isActive ? 'active' : 'inactive'}`}>
                      {c.status_name}
                    </span>
                  )}
                  {c.legal_type_name && (
                    <>
                      <span className="person-company-meta-sep">·</span>
                      <span className="person-company-legal-type">{c.legal_type_name}</span>
                    </>
                  )}
                  {c.city && (
                    <>
                      <span className="person-company-meta-sep">·</span>
                      <span className="person-company-city">{c.city}</span>
                    </>
                  )}
                  {c.afm && (
                    <>
                      <span className="person-company-meta-sep">·</span>
                      <span>ΑΦΜ: {c.afm}</span>
                    </>
                  )}
                </div>
              </div>
              <div className="person-role-info">
                {inv.role && <div className="person-role-badge">{inv.role}</div>}
                {(inv.date_from || inv.date_to) && (
                  <div className="person-role-dates">
                    {t('personPage.roleDates', { from: inv.date_from || '—', to: inv.date_to || 'σήμερα' })}
                  </div>
                )}
                {(inv.is_representative_alone || inv.is_representative_in_common) && (
                  <div className="repr-badges">
                    {inv.is_representative_alone && (
                      <span className="repr-badge alone" title={t('personPage.representsAloneTitle')}>{t('personPage.representsAloneBadge')}</span>
                    )}
                    {inv.is_representative_in_common && (
                      <span className="repr-badge common" title={t('personPage.representsInCommonTitle')}>{t('personPage.representsInCommonBadge')}</span>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default PersonPage;
