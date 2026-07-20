import React from 'react';
import { ReactComponent as LogoSvg } from '../assets/logo.svg';

/**
 * LogoGlyph — Wraps the SVG artwork (src/assets/logo.svg) as a React
 * component so callers can control size, colour, and CSS classes.
 *
 * The SVG itself uses `currentColor` for all fills & strokes, so
 * setting `color` on this component's parent (or passing the `color`
 * prop which maps to the CSS `color` attribute) automatically themes
 * the graphic.
 *
 * To edit the artwork, open src/assets/logo.svg in any SVG editor
 * (Figma, Illustrator, InkScape, or just a text editor).  After
 * saving, both <Logo> and <LogoGlyph> pick up the changes immediately
 * — no code changes needed.
 *
 * @param {number}  size      - width & height in pixels (default 30)
 * @param {string}  color     - CSS colour value applied to the <svg>
 *                              element.  Because the internal shapes
 *                              use `currentColor`, this maps directly.
 *                              Defaults to 'currentColor' (inherits
 *                              from parent's CSS `color`).
 * @param {string}  className - optional CSS class(es) on the <svg>
 */
const LogoGlyph = ({ size = 30, color = 'currentColor', className }) => (
  <LogoSvg
    width={size}
    height={size}
    style={{ color }}
    className={className}
    role="img"
    aria-label="Crati logo"
  />
);

export default LogoGlyph;
