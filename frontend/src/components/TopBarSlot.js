import { createPortal } from 'react-dom';

/**
 * TopBarSlot — renders children into the fixed top-bar area (to the right
 * of the logo) via a React Portal.
 *
 * Usage from any page:
 *   <TopBarSlot>
 *     <span>My page header</span>
 *   </TopBarSlot>
 *
 * Returns null when the portal target (#top-bar-slot) hasn't mounted yet.
 */
const TopBarSlot = ({ children }) => {
  const target = document.getElementById('top-bar-slot');
  if (!target) return null;
  return createPortal(children, target);
};

export default TopBarSlot;
