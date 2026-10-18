import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Monitor, Sun, Moon, Palette, Save } from 'lucide-react';
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
          <h3><Palette size={16} /> Personalize Your Experience</h3>
          <p>
            Choose to follow your system's appearance, pick between light and dark modes,
            then choose your favorite color palette.
            Your preferences will be saved and applied across the entire application.
          </p>

          <div className="features-list">
            <div className="feature-item">
              <Monitor size={14} /> <strong>System Mode:</strong> Automatically matches your device's light/dark preference
            </div>
            <div className="feature-item">
              <Moon size={14} /> <strong>Dark Mode:</strong> Easy on the eyes for low-light environments
            </div>
            <div className="feature-item">
              <Sun size={14} /> <strong>Light Mode:</strong> Clean and bright for daytime use
            </div>
            <div className="feature-item">
              <Palette size={14} /> <strong>Color Palettes:</strong> 6 beautiful color schemes to match your style
            </div>
            <div className="feature-item">
              <Save size={14} /> <strong>Auto-Save:</strong> Your preferences are automatically saved
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ThemeSettings;
