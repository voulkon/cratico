import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * Custom hook to manage filter state synchronized with URL parameters
 * Handles: sort, search, types, roles, amounts, organizations, date range, direct assignments
 */
const useUrlFilters = (defaultValues = {}) => {
  const [searchParams, setSearchParams] = useSearchParams();

  // Initialize state from URL or defaults
  const [sortBy, setSortBy] = useState(
    searchParams.get('sort') || defaultValues.sortBy || 'amount_desc'
  );
  const [searchQuery, setSearchQuery] = useState(
    searchParams.get('search') || defaultValues.searchQuery || ''
  );
  const [selectedTypes, setSelectedTypes] = useState(
    searchParams.get('types') ? searchParams.get('types').split(',') : (defaultValues.selectedTypes || [])
  );
  const [selectedRoles, setSelectedRoles] = useState(
    searchParams.get('roles') ? searchParams.get('roles').split(',') : (defaultValues.selectedRoles || [])
  );
  const [selectedOrgs, setSelectedOrgs] = useState(
    searchParams.get('orgs') ? searchParams.get('orgs').split(',') : (defaultValues.selectedOrgs || [])
  );
  const [amountFilters, setAmountFilters] = useState({
    minAmount: searchParams.get('minAmount') || defaultValues.minAmount || '',
    maxAmount: searchParams.get('maxAmount') || defaultValues.maxAmount || ''
  });
  const [directAssignmentsOnly, setDirectAssignmentsOnly] = useState(
    searchParams.get('direct_assignments_only') === 'true' || defaultValues.directAssignmentsOnly || false
  );

  // Sync state with URL when params change
  // We intentionally only listen to searchParams changes to avoid circular updates
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    const urlSort = searchParams.get('sort');
    const urlSearch = searchParams.get('search') || '';
    const urlTypes = searchParams.get('types') ? searchParams.get('types').split(',') : [];
    const urlRoles = searchParams.get('roles') ? searchParams.get('roles').split(',') : [];
    const urlOrgs = searchParams.get('orgs') ? searchParams.get('orgs').split(',') : [];
    const urlMinAmount = searchParams.get('minAmount') || '';
    const urlMaxAmount = searchParams.get('maxAmount') || '';
    const urlDirectAssignmentsOnly = searchParams.get('direct_assignments_only') === 'true';

    if (urlSort && urlSort !== sortBy) setSortBy(urlSort);
    if (urlSearch !== searchQuery) setSearchQuery(urlSearch);
    if (JSON.stringify(urlTypes) !== JSON.stringify(selectedTypes)) setSelectedTypes(urlTypes);
    if (JSON.stringify(urlRoles) !== JSON.stringify(selectedRoles)) setSelectedRoles(urlRoles);
    if (JSON.stringify(urlOrgs) !== JSON.stringify(selectedOrgs)) setSelectedOrgs(urlOrgs);
    if (urlMinAmount !== amountFilters.minAmount || urlMaxAmount !== amountFilters.maxAmount) {
      setAmountFilters({ minAmount: urlMinAmount, maxAmount: urlMaxAmount });
    }
    if (urlDirectAssignmentsOnly !== directAssignmentsOnly) setDirectAssignmentsOnly(urlDirectAssignmentsOnly);
  }, [searchParams]);

  // Update URL with current filter state
  const updateUrl = useCallback((updates = {}) => {
    const newParams = new URLSearchParams();

    const finalSort = updates.sortBy !== undefined ? updates.sortBy : sortBy;
    const finalSearch = updates.searchQuery !== undefined ? updates.searchQuery : searchQuery;
    const finalTypes = updates.selectedTypes !== undefined ? updates.selectedTypes : selectedTypes;
    const finalRoles = updates.selectedRoles !== undefined ? updates.selectedRoles : selectedRoles;
    const finalOrgs = updates.selectedOrgs !== undefined ? updates.selectedOrgs : selectedOrgs;
    const finalAmountFilters = updates.amountFilters !== undefined ? updates.amountFilters : amountFilters;
    const finalDirectAssignmentsOnly = updates.directAssignmentsOnly !== undefined ? updates.directAssignmentsOnly : directAssignmentsOnly;

    if (finalSort && finalSort !== 'recent') newParams.set('sort', finalSort);
    if (finalSearch) newParams.set('search', finalSearch);
    if (finalTypes.length > 0) newParams.set('types', finalTypes.join(','));
    if (finalRoles.length > 0) newParams.set('roles', finalRoles.join(','));
    if (finalOrgs.length > 0) newParams.set('orgs', finalOrgs.join(','));
    if (finalAmountFilters.minAmount) newParams.set('minAmount', finalAmountFilters.minAmount);
    if (finalAmountFilters.maxAmount) newParams.set('maxAmount', finalAmountFilters.maxAmount);
    if (finalDirectAssignmentsOnly) newParams.set('direct_assignments_only', 'true');

    setSearchParams(newParams);
  }, [sortBy, searchQuery, selectedTypes, selectedRoles, selectedOrgs, amountFilters, directAssignmentsOnly, setSearchParams]);

  // Helper functions
  const toggleType = useCallback((type) => {
    const newTypes = selectedTypes.includes(type)
      ? selectedTypes.filter(t => t !== type)
      : [...selectedTypes, type];
    setSelectedTypes(newTypes);
    updateUrl({ selectedTypes: newTypes });
  }, [selectedTypes, updateUrl]);

  const toggleRole = useCallback((role) => {
    const newRoles = selectedRoles.includes(role)
      ? selectedRoles.filter(r => r !== role)
      : [...selectedRoles, role];
    setSelectedRoles(newRoles);
    updateUrl({ selectedRoles: newRoles });
  }, [selectedRoles, updateUrl]);

  const toggleOrg = useCallback((org) => {
    const newOrgs = selectedOrgs.includes(org)
      ? selectedOrgs.filter(o => o !== org)
      : [...selectedOrgs, org];
    setSelectedOrgs(newOrgs);
    updateUrl({ selectedOrgs: newOrgs });
  }, [selectedOrgs, updateUrl]);

  const clearAllFilters = useCallback(() => {
    setSelectedTypes([]);
    setSelectedRoles([]);
    setSelectedOrgs([]);
    setSearchQuery('');
    setAmountFilters({ minAmount: '', maxAmount: '' });
    setDirectAssignmentsOnly(false);
    updateUrl({
      selectedTypes: [],
      selectedRoles: [],
      selectedOrgs: [],
      searchQuery: '',
      amountFilters: { minAmount: '', maxAmount: '' },
      directAssignmentsOnly: false
    });
  }, [updateUrl]);

  // Calculate active filters count
  const activeFiltersCount =
    selectedTypes.length +
    selectedRoles.length +
    selectedOrgs.length +
    (amountFilters.minAmount ? 1 : 0) +
    (amountFilters.maxAmount ? 1 : 0) +
    (searchQuery ? 1 : 0) +
    (directAssignmentsOnly ? 1 : 0);

  return {
    // State
    sortBy,
    searchQuery,
    selectedTypes,
    selectedRoles,
    selectedOrgs,
    amountFilters,
    directAssignmentsOnly,
    activeFiltersCount,

    // Setters
    setSortBy: (value) => {
      setSortBy(value);
      updateUrl({ sortBy: value });
    },
    setSearchQuery: (value) => {
      setSearchQuery(value);
      updateUrl({ searchQuery: value });
    },
    setAmountFilters: (value) => {
      setAmountFilters(value);
      updateUrl({ amountFilters: value });
    },
    setDirectAssignmentsOnly: (value) => {
      setDirectAssignmentsOnly(value);
      updateUrl({ directAssignmentsOnly: value });
    },

    // Togglers
    toggleType,
    toggleRole,
    toggleOrg,

    // Utilities
    updateUrl,
    clearAllFilters
  };
};

export default useUrlFilters;
