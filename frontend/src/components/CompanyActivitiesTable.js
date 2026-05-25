import React, { useState } from 'react';
import './CompanyActivitiesTable.css';

const CompanyActivitiesTable = ({ activities }) => {
  const [isOpen, setIsOpen] = useState(false);

  if (!activities || activities.length === 0) return null;

  // Sort: primary (Κύρια) first
  const sorted = [...activities].sort((a, b) => {
    if (a.activity_type === 'Κύρια') return -1;
    if (b.activity_type === 'Κύρια') return 1;
    return 0;
  });

  const primaryActivity = sorted.find(a => a.activity_type === 'Κύρια');

  return (
    <div className="company-activities-table">
      <button className="section-toggle" onClick={() => setIsOpen(!isOpen)}>
        <span className="section-toggle-label">
          Δραστηριότητες (ΚΑΔ)
          <span className="section-toggle-count">{activities.length}</span>
          {!isOpen && primaryActivity && (
            <span className="section-toggle-preview">{primaryActivity.activity_name}</span>
          )}
        </span>
        <span className="toggle-arrow">{isOpen ? '▲' : '▼'}</span>
      </button>
      {isOpen && (
      <div className="activities-table-wrapper">
        <table>
          <thead>
            <tr>
              <th>ΚΑΔ</th>
              <th>Περιγραφή</th>
              <th>Τύπος</th>
              <th>Από</th>
              <th>Έως</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((activity, index) => (
              <tr key={index} className={activity.activity_type === 'Κύρια' ? 'primary-activity' : ''}>
                <td className="activity-code">{activity.activity_id}</td>
                <td className="activity-name">{activity.activity_name}</td>
                <td>
                  <span className={`activity-type-badge ${activity.activity_type === 'Κύρια' ? 'primary' : 'secondary'}`}>
                    {activity.activity_type}
                  </span>
                </td>
                <td className="activity-date">{activity.date_from || '—'}</td>
                <td className="activity-date">{activity.date_to || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}
    </div>
  );
};

export default CompanyActivitiesTable;
