import React from 'react';
import { Link } from 'react-router-dom';
import './Logo.css';

const Logo = ({ size = 'medium' }) => {
  return (
    <Link to="/" className={`logo-link logo-${size}`}>
      <span className="logo-text">
        <span className="logo-crati">C<span className="logo-rest">rati</span></span>
        <span className="logo-dot">.</span>
        <span className="logo-co">C<span className="logo-rest">o</span></span>
      </span>
    </Link>
  );
};

export default Logo;
