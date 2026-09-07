import React, { useState } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import AuthModal from './AuthModal';
import UserMenuDropdown from './UserMenuDropdown';
import SplitButton from './SplitButton';
import { UserIcon } from './Icons';
import './UserMenu.css';

const UserMenu = ({ isOpen, onToggle }) => {
  const [showLoginForm, setShowLoginForm] = useState(false);
  const { palette, palettes, theme } = useTheme();
  const { user, isSignedIn, isClerkAuth } = useAuth();

  const getCurrentPaletteColor = () => {
    const currentPalette = palettes.find(p => p.id === palette);
    if (!currentPalette) return '#4299E1';
    const isDarkTheme = theme === 'dark' || theme === 'solarized-dark';
    return isDarkTheme ? currentPalette.darkColor : currentPalette.color;
  };

  const handleToggleMenu = () => {
    onToggle();
  };

  const handleCloseMenu = () => {
    if (isOpen) {
      onToggle();
    }
  };

  const buttonStyle = {
    borderLeft: `3px solid ${getCurrentPaletteColor()}`
  };

  return (
    <>
      <div className={`user-menu ${isOpen ? 'user-menu-open' : ''} ${isSignedIn ? 'user-menu-authenticated' : ''}`}>
        <div
          className="user-menu-wrapper"
          style={buttonStyle}
        >
          <SplitButton
            isOpen={isOpen}
            onMainClick={handleToggleMenu}
            onChevronClick={handleToggleMenu}
            mainClassName="user-menu-trigger"
            chevronClassName="user-menu-chevron"
            className="user-menu-split-btn"
            mainTitle={isOpen ? 'Close menu' : 'Open menu'}
            chevronTitle={isOpen ? 'Close menu' : 'Open menu'}
          >
            <div className="user-avatar">
              {isSignedIn && user?.imageUrl ? (
                <img src={user.imageUrl} alt={user.firstName} className="avatar-image" />
              ) : (
                <div className="avatar-placeholder">
                  {isSignedIn && user?.firstName ? user.firstName.charAt(0).toUpperCase() : <UserIcon size={16} />}
                </div>
              )}
            </div>
          </SplitButton>
        </div>

        {isOpen && (
          <UserMenuDropdown
            onClose={handleCloseMenu}
            onShowLogin={() => setShowLoginForm(true)}
          />
        )}

        {/* Auth modal — self-contained login/register/reset switching */}
        {showLoginForm && !isClerkAuth && (
          <AuthModal
            onSuccess={() => setShowLoginForm(false)}
            onCancel={() => setShowLoginForm(false)}
          />
        )}
      </div>
    </>
  );
};

export default UserMenu;
