import React, { useState } from 'react';
import { useTranslation } from '../contexts/TranslationContext';
import './CompanyPersonsTable.css';

const CompanyPersonsTable = ({ persons }) => {
  const [isOpen, setIsOpen] = useState(true);
  const { t } = useTranslation();

  if (!persons || persons.length === 0) return null;

  return (
    <div className="company-persons-table">
      <button className="section-toggle" onClick={() => setIsOpen(!isOpen)}>
        <span className="section-toggle-label">
          {t('companyPersonsTable.sectionTitle')}
          <span className="section-toggle-count">{persons.length}</span>
        </span>
        <span className="toggle-arrow">{isOpen ? '▲' : '▼'}</span>
      </button>
      {isOpen && (
      <div className="persons-table-wrapper">
        <table>
          <thead>
            <tr>
              <th>{t('companyPersonsTable.columnName')}</th>
              <th>{t('companyPersonsTable.columnRole')}</th>
              <th>{t('companyPersonsTable.columnFrom')}</th>
              <th>{t('companyPersonsTable.columnTo')}</th>
              <th>{t('companyPersonsTable.columnRepresentation')}</th>
            </tr>
          </thead>
          <tbody>
            {persons.map((person, index) => (
              <tr key={index}>
                <td className="person-name">
                  {person.person_name || person.business_name || '—'}
                  {person.person_name && person.business_name && (
                    <div className="business-name-secondary">{person.business_name}</div>
                  )}
                </td>
                <td className="person-role">{person.role || '—'}</td>
                <td className="person-date">{person.date_from || '—'}</td>
                <td className="person-date">{person.date_to || '—'}</td>
                <td className="person-repr">
                  {person.is_representative_alone && (
                    <span className="repr-badge alone" title={t('companyPersonsTable.representsAloneTitle')}>{t('companyPersonsTable.representsAloneBadge')}</span>
                  )}
                  {person.is_representative_in_common && (
                    <span className="repr-badge common" title={t('companyPersonsTable.representsInCommonTitle')}>{t('companyPersonsTable.representsInCommonBadge')}</span>
                  )}
                  {!person.is_representative_alone && !person.is_representative_in_common && (
                    <span className="repr-none">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}
    </div>
  );
};

export default CompanyPersonsTable;
