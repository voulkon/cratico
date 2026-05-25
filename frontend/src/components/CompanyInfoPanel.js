import React, { useState } from 'react';
import './CompanyInfoPanel.css';

const CompanyInfoPanel = ({ company }) => {
  const [showObjective, setShowObjective] = useState(false);
  const [showDetails, setShowDetails] = useState(true);

  if (!company) return null;

  const address = [
    company.street,
    company.street_number && company.street_number !== '0' ? company.street_number : null,
    company.city,
    company.zip_code,
  ]
    .filter(Boolean)
    .join(', ');

  const businessPortalUrl = `https://publicity.businessportal.gr/company/${company.ar_gemi}`;

  return (
    <div className="company-info-panel">
      <div className="company-info-header">
        <div className="company-header-top">
          <div className="company-header-names">
            <h2 className="company-primary-name">
              {company.co_name_el || company.co_names_en?.[0] || '—'}
            </h2>
            {company.co_names_en?.[0] && company.co_name_el && (
              <div className="company-name-en">{company.co_names_en[0]}</div>
            )}
            {company.co_titles_el?.length > 0 && (
              <div className="company-titles">
                {company.co_titles_el.map((t, i) => (
                  <span key={i} className="company-title-badge">{t}</span>
                ))}
              </div>
            )}
          </div>
          <div className="company-header-actions">
            <a
              href={businessPortalUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="source-link"
              title="Προβολή στο Business Portal"
            >
              Business Portal ↗
            </a>
            <button className="section-toggle inline" onClick={() => setShowDetails(!showDetails)}>
              {showDetails ? '▲ Απόκρυψη' : '▼ Προβολή στοιχείων'}
            </button>
          </div>
        </div>
      </div>

      {showDetails && (
        <>
          <div className="company-info-grid">
            <div className="company-info-item">
              <span className="info-label">ΓΕΜΗ</span>
              <span className="info-value mono">{company.ar_gemi}</span>
            </div>
            <div className="company-info-item">
              <span className="info-label">ΑΦΜ</span>
              <span className="info-value mono">{company.afm}</span>
            </div>
            <div className="company-info-item">
              <span className="info-label">Νομική Μορφή</span>
              <span className="info-value">{company.legal_type_name || '—'}</span>
            </div>
            <div className="company-info-item">
              <span className="info-label">Κατάσταση</span>
              <span className={`info-value status-badge ${company.status_name === 'Ενεργή' ? 'active' : 'inactive'}`}>
                {company.status_name || '—'}
              </span>
            </div>
            <div className="company-info-item">
              <span className="info-label">Ημ/νία Ίδρυσης</span>
              <span className="info-value">{company.incorporation_date || '—'}</span>
            </div>
            <div className="company-info-item">
              <span className="info-label">Τελ. Αλλαγή Κατάστασης</span>
              <span className="info-value">{company.last_status_change || '—'}</span>
            </div>
            {address && (
              <div className="company-info-item full-width">
                <span className="info-label">Διεύθυνση</span>
                <span className="info-value">{address}</span>
              </div>
            )}
            {company.municipality_name && (
              <div className="company-info-item">
                <span className="info-label">Δήμος</span>
                <span className="info-value">{company.municipality_name}</span>
              </div>
            )}
            {company.prefecture_name && (
              <div className="company-info-item">
                <span className="info-label">Περιφέρεια</span>
                <span className="info-value">{company.prefecture_name}</span>
              </div>
            )}
            {company.email && (
              <div className="company-info-item">
                <span className="info-label">Email</span>
                <a href={`mailto:${company.email}`} className="info-value info-link">{company.email}</a>
              </div>
            )}
            {company.url && (
              <div className="company-info-item">
                <span className="info-label">Website</span>
                <a
                  href={company.url.startsWith('http') ? company.url : `https://${company.url}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="info-value info-link"
                >
                  {company.url}
                </a>
              </div>
            )}
            {company.gemi_office_name && (
              <div className="company-info-item full-width">
                <span className="info-label">Υπηρεσία ΓΕΜΗ</span>
                <span className="info-value">{company.gemi_office_name}</span>
              </div>
            )}
            {company.branch_gemi_numbers?.length > 0 && (
              <div className="company-info-item">
                <span className="info-label">Υποκαταστήματα</span>
                <span className="info-value">{company.branch_gemi_numbers.length}</span>
              </div>
            )}
          </div>

          {company.objective && (
            <div className="company-objective">
              <button
                className="objective-toggle"
                onClick={() => setShowObjective(!showObjective)}
              >
                Σκοπός Εταιρείας {showObjective ? '▲' : '▼'}
              </button>
              {showObjective && (
                <div className="objective-text">{company.objective}</div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default CompanyInfoPanel;
