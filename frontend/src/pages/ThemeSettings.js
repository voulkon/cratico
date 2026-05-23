import React from 'react';
import { useNavigate } from 'react-router-dom';
import ThemeSwitcher from '../components/ThemeSwitcher';
import './ThemeSettings.css';

const ThemeSettings = () => {
  const navigate = useNavigate();

  return (
    <div className="theme-settings-page">
      <div className="settings-header">
        <button onClick={() => navigate(-1)} className="back-button">
          ← Back
        </button>
        <h1>Theme & Appearance Settings</h1>
      </div>

      <div className="settings-content">
        <ThemeSwitcher />

        <div className="settings-info">
          <h3>🎨 Personalize Your Experience</h3>
          <p>
            Choose between light and dark modes, then pick your favorite color palette.
            Your preferences will be saved and applied across the entire application.
          </p>

          <div className="features-list">
            <div className="feature-item">
              <strong>🌙 Dark Mode:</strong> Easy on the eyes for low-light environments
            </div>
            <div className="feature-item">
              <strong>☀️ Light Mode:</strong> Clean and bright for daytime use
            </div>
            <div className="feature-item">
              <strong>🎨 Color Palettes:</strong> 6 beautiful color schemes to match your style
            </div>
            <div className="feature-item">
              <strong>💾 Auto-Save:</strong> Your preferences are automatically saved
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ThemeSettings;
