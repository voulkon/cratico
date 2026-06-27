import React from 'react';
import {
  OrganizationIcon,
  PenIcon,
  UnitIcon,
  CompanyIcon,
  UserIcon,
  FileIcon,
  TimerIcon,
} from '../components/Icons';

/**
 * Canonical category metadata shared by CategoryTabs, BrowsePage, and SuperSearch.
 *
 * Keys cover both the URL‑facing singular forms (BrowsePage) and the API‑returned
 * snake_case forms (SuperSearch).  Consumers pick whichever key set they need.
 */
export const CATEGORY_META = {
  // ── API / SuperSearch keys (snake_case, plural) ──────────────────
  organizations:    { label: 'Organizations',    Icon: OrganizationIcon },
  signers:          { label: 'Signers',           Icon: PenIcon },
  units:            { label: 'Units',             Icon: UnitIcon },
  companies:        { label: 'Companies',         Icon: CompanyIcon },
  company_persons:  { label: 'Company Persons',   Icon: UserIcon },
  afm_entities:     { label: 'AFM Entities',      Icon: CompanyIcon },
  documents:        { label: 'Documents',         Icon: FileIcon },
  recently_visited: { label: 'Recently Visited',  Icon: TimerIcon },

  // ── URL / BrowsePage keys (singular) ─────────────────────────────
  organization:  { label: 'Organizations',  Icon: OrganizationIcon },
  signer:        { label: 'Signers',        Icon: PenIcon },
  unit:          { label: 'Units',          Icon: UnitIcon },
  company:       { label: 'Companies',      Icon: CompanyIcon },
  companyperson: { label: 'People',         Icon: UserIcon },
  afmentity:     { label: 'AFM Entities',   Icon: CompanyIcon },

  // ── Item‑type keys (as returned inside SuperSearch results) ──────
  // These match the singular item `type` field (e.g. "organization", "company_person").
  // They are identical to the URL keys above except for `company_person`.
  company_person: { label: 'Company Person', Icon: UserIcon },
  document:       { label: 'Document',       Icon: FileIcon },
};

/**
 * Return a React icon element for a given category / item‑type key.
 *
 * @param {string}  key  – one of the keys in CATEGORY_META
 * @param {number}  size – icon size in px (default 14)
 * @returns {React.Element|null}
 */
export function getCategoryIcon(key, size = 14) {
  const meta = CATEGORY_META[key];
  if (!meta) return null;
  const { Icon } = meta;
  return React.createElement(Icon, { size });
}

/**
 * Return the human‑readable label for a category / item‑type key.
 *
 * @param {string} key – one of the keys in CATEGORY_META
 * @returns {string}
 */
export function getCategoryLabel(key) {
  return CATEGORY_META[key]?.label || key;
}
