import React from 'react';
import { ReactComponent as LogoSvg } from '../assets/logo.svg';

/**
 * LogoGlyph — Wraps the SVG artwork (src/assets/logo.svg) as a React
 * component so callers can control size, colour, stroke widths, and
 * CSS classes.
 *
 * The SVG itself uses `currentColor` for all fills & strokes, so
 * setting `color` on this component's parent (or passing the `color`
 * prop which maps to the CSS `color` attribute) automatically themes
 * the graphic.
 *
 * Two independent stroke widths are exposed via CSS custom properties:
 *   --logo-stroke-surrounding  (magnifier ring & handle)
 *   --logo-stroke-column       (inner column details)
 * Set them through the strokeSurrounding / strokeColumn props (in px)
 * or override in your browser's devtools for quick experimentation.
 *
 * To replace the artwork, export from Canva as SVG, then run:
 *   ./scripts/process-svg.sh raw.svg src/assets/logo.svg --strip-stroke-width
 *
 * @param {number}  size              - width & height in pixels (default 30)
 * @param {string}  color             - CSS colour value applied to the <svg>
 *                                      element.  Because the internal shapes
 *                                      use `currentColor`, this maps directly.
 *                                      Defaults to 'currentColor' (inherits
 *                                      from parent's CSS `color`).
 * @param {number}  strokeSurrounding - magnifier stroke width in px.
 *                                      Defaults to undefined (CSS default 5px).
 * @param {number}  strokeColumn      - column stroke width in px.
 *                                      Defaults to undefined (CSS default 2.5px).
 * @param {string}  className         - optional CSS class(es) on the <svg>
 */
const LogoGlyph = ({
  size = 30,
  color = 'currentColor',
  strokeSurrounding,
  strokeColumn,
  className,
}) => {
  const style = { color };
  if (strokeSurrounding !== undefined) {
    style['--logo-stroke-surrounding'] = `${strokeSurrounding}px`;
  }
  if (strokeColumn !== undefined) {
    style['--logo-stroke-column'] = `${strokeColumn}px`;
  }

  return (
    <LogoSvg
      width={size}
      height={size}
      style={style}
      className={className}
      role="img"
      aria-label="Crati logo"
    />
  );
};

export default LogoGlyph;
