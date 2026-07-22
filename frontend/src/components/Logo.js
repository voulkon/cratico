import React from 'react';
import { Link } from 'react-router-dom';
import LogoGlyph from './LogoGlyph';
import './Logo.css';

/**
 * Logo — Clickable home-link that wraps the LogoGlyph SVG.
 *
 * @param {number|string} size - SVG pixel size, or preset key:
 *   'small' (20), 'medium' (30), 'large' (40).  Defaults to 'medium'.
 * @param {string} color - CSS colour value passed through to LogoGlyph.
 *   Defaults to 'currentColor' (theme-aware via parent CSS).
 * @param {number} strokeSurrounding - magnifier stroke px, forwarded to LogoGlyph.
 * @param {number} strokeColumn - column stroke px, forwarded to LogoGlyph.
 * @param {string} className - optional additional CSS class(es).
 */
const SIZE_MAP = { small: 20, medium: 30, large: 40 };

const Logo = ({ size = 'medium', color = 'currentColor', strokeSurrounding, strokeColumn, className }) => {
  const px = typeof size === 'number' ? size : (SIZE_MAP[size] ?? SIZE_MAP.medium);
  const sizeKey = typeof size === 'string' ? size : 'medium';

  return (
    <Link
      to="/"
      className={`logo-link logo-${sizeKey}${className ? ` ${className}` : ''}`}
      aria-label="Home"
    >
      <LogoGlyph
        size={px}
        color={color}
        strokeSurrounding={strokeSurrounding}
        strokeColumn={strokeColumn}
      />
    </Link>
  );
};

export default Logo;
