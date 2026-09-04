import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { streamSearch, getDefaultSuggestions, searchCategories, trackSearchSelection, getRecentlyVisited, clearSearchHistory, deleteSingleHistoryItem } from '../api/searchApi';
import { TimerIcon, TrashIcon, SearchIcon } from './Icons.js';
import CategoryTabs from './CategoryTabs';
import { getCategoryIcon, getCategoryLabel } from '../constants/categoryDefinitions';
import { useAuthConfig } from '../contexts/AuthConfigContext';
import './SuperSearch.css';

const SuperSearch = ({
  placeholder = "Search organizations, documents, companies...",
  onResultClick,
  showFullResults = true,
  autoFocus = false,
  className = ""
}) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [showResults, setShowResults] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [selectedCategory, setSelectedCategory] = useState('all'); // 'all' or specific category name
  const [categoryLimits, setCategoryLimits] = useState({
    organizations: 5,
    signers: 5,
    units: 5,
    companies: 5,
    company_persons: 5,
    documents: 5,
    afm_entities: 5
  });
  const [hasMoreResults, setHasMoreResults] = useState({
    organizations: true,
    signers: true,
    units: true,
    companies: true,
    company_persons: true,
    documents: true,
    afm_entities: true
  });

  const navigate = useNavigate();
  // Backend-controlled search debounce (SEARCH_DEBOUNCE_MS feature flag,
  // delivered via /api/system/config/auth/). Falls back to 300ms while the
  // config is loading or if the endpoint is unavailable.
  const { searchDebounceMs } = useAuthConfig();
  const debounceMsRef = useRef(300);
  debounceMsRef.current = searchDebounceMs ?? 300;
  const inputRef = useRef(null);
  const resultsRef = useRef(null);
  const searchTimeoutRef = useRef(null);
  const abortControllerRef = useRef(null);
  const currentResultsRef = useRef(null);
  const loadMoreObserverRef = useRef(null);
  const loadMoreTriggerRef = useRef(null);
  const loadMoreCallbackRef = useRef(null);

  // Auto focus if requested
  useEffect(() => {
    if (autoFocus && inputRef.current) {
      inputRef.current.focus();
    }
  }, [autoFocus]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  // Keep ref in sync with results state
  useEffect(() => {
    currentResultsRef.current = results;
  }, [results]);

  // Debounced search function
  const performSearch = useCallback(async (searchQuery) => {
    if (!searchQuery.trim()) {
      setResults(null);
      setShowResults(false);
      return;
    }

    // Abort any in-flight request before starting a new one
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    // Create a new AbortController for this search
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setIsLoading(true);
    setDocumentsLoading(false);

    try {
      // Start streaming search with the abort signal
      streamSearch(searchQuery, {
        includeDocuments: showFullResults,
        limit: 5,
        signal: controller.signal,

        // Handle entity results (fast)
        onEntities: (entityData) => {
          setResults(prevResults => {
            // Merge entity results with existing results
            const newResults = {
              query: entityData.query,
              results: { ...entityData.results },
              total_count: entityData.total_count
            };

            // If we already have document results, merge them
            if (prevResults?.results?.documents) {
              newResults.results.documents = prevResults.results.documents;
              newResults.total_count += prevResults.results.documents.length;
            }

            return newResults;
          });

          // Check initial results to see if any categories have fewer than requested
          const initialHasMore = {
            organizations: (entityData.results.organizations?.length || 0) >= 5,
            signers: (entityData.results.signers?.length || 0) >= 5,
            units: (entityData.results.units?.length || 0) >= 5,
            companies: (entityData.results.companies?.length || 0) >= 5,
            company_persons: (entityData.results.company_persons?.length || 0) >= 5,
            afm_entities: (entityData.results.afm_entities?.length || 0) >= 5,
            documents: true // Will be updated when documents arrive
          };
          setHasMoreResults(initialHasMore);

          // Auto-select first category with results
          const firstCategory = Object.keys(entityData.results).find(
            key => entityData.results[key] && entityData.results[key].length > 0
          );
          if (firstCategory) {
            setSelectedCategory(firstCategory);
          }

          setShowResults(true);
          setIsLoading(false);
          setDocumentsLoading(showFullResults); // Start loading documents indicator
        },

        // Handle document results (slow)
        onDocuments: (documentData) => {
          setResults(prevResults => {
            if (!prevResults) return documentData;

            // Merge document results with entity results
            return {
              query: prevResults.query,
              results: {
                ...prevResults.results,
                documents: documentData.results.documents || []
              },
              total_count: prevResults.total_count + (documentData.results.documents?.length || 0)
            };
          });

          // Update hasMoreResults for documents
          setHasMoreResults(prev => ({
            ...prev,
            documents: (documentData.results.documents?.length || 0) >= 5
          }));

          setDocumentsLoading(false);
        },

        // Handle completion
        onDone: () => {
          setDocumentsLoading(false);
          setIsLoading(false);
          abortControllerRef.current = null;
        },

        // Handle errors
        onError: (error) => {
          console.error('Search stream failed:', error);
          setIsLoading(false);
          setDocumentsLoading(false);
          abortControllerRef.current = null;

          // Show error state but don't hide existing results
          if (!currentResultsRef.current) {
            setResults({
              query: searchQuery,
              results: {},
              total_count: 0,
              error: error.message
            });
          }
        }
      });

    } catch (error) {
      // Ignore cancellation errors from AbortController
      if (error?.code !== 'ERR_CANCELED') {
        console.error('Search initialization failed:', error);
        setIsLoading(false);
        setDocumentsLoading(false);
        setResults(null);
        setShowResults(false);
      }
    }
  }, [showFullResults]);

  // Load more results for a specific category or all categories
  const loadMoreResults = useCallback(async () => {
    if (!query.trim()) return;

    // Check if already loading (use ref to avoid adding to dependencies)
    if (isLoading) {
      console.log('Already loading, skipping');
      return;
    }

    // Check if we should load more based on selected category
    if (selectedCategory === 'all') {
      // If all categories have no more results, don't load
      const hasAnyMore = Object.values(hasMoreResults).some(v => v === true);
      if (!hasAnyMore) {
        console.log('All categories exhausted');
        return;
      }
      console.log('Loading more from all categories with remaining results');
    } else {
      // If the selected category has no more results, don't load
      if (!hasMoreResults[selectedCategory]) {
        console.log(`Category ${selectedCategory} exhausted`);
        return;
      }
      console.log(`Loading more from ${selectedCategory}`);
    }

    try {
      // Abort any in-flight request before loading more
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      const controller = new AbortController();
      abortControllerRef.current = controller;

      setIsLoading(true);

      // Determine which categories to increase limits for.
      // Only categories being extended are requested from the API
      // (others are set to 0 = not requested), so we never re-fetch
      // results we already have.
      const newLimits = { ...categoryLimits };

      if (selectedCategory === 'all') {
        // Increase all category limits that still have more results
        Object.keys(newLimits).forEach(key => {
          if (hasMoreResults[key]) {
            newLimits[key] += 5;
          } else {
            newLimits[key] = 0;
          }
        });
      } else {
        // Request ONLY the selected category
        Object.keys(newLimits).forEach(key => {
          newLimits[key] = key === selectedCategory ? newLimits[key] + 5 : 0;
        });
      }

      // Fetch with new limits (only extended categories are sent to the API)
      const newResults = await searchCategories(query, newLimits, controller.signal);

      // Check which categories have reached their end
      const newHasMoreResults = { ...hasMoreResults };
      Object.keys(newLimits).forEach(category => {
        const resultsKey = category; // e.g., 'organizations'
        const currentCount = newResults.results[resultsKey]?.length || 0;
        const requestedLimit = newLimits[category];

        // If we got fewer results than requested, we've reached the end
        if (currentCount < requestedLimit) {
          newHasMoreResults[category] = false;
        }
      });

      // Merge: keep results from categories we did NOT re-request,
      // replace the ones we extended with the fresh (longer) lists.
      setResults(prevResults => {
        if (!prevResults) return newResults;
        const mergedResults = { ...prevResults.results };
        Object.entries(newResults.results).forEach(([category, items]) => {
          if (newLimits[category] > 0) {
            mergedResults[category] = items;
          }
        });
        return {
          ...prevResults,
          results: mergedResults,
          total_count: Object.values(mergedResults).reduce(
            (sum, items) => sum + (items?.length || 0),
            0
          )
        };
      });
      setCategoryLimits(newLimits);
      setHasMoreResults(newHasMoreResults);
      setIsLoading(false);
    } catch (error) {
      if (error?.code !== 'ERR_CANCELED') {
        console.error('Load more failed:', error);
      }
      setIsLoading(false);
    }
  }, [query, categoryLimits, selectedCategory, hasMoreResults, isLoading]);

  // Store the callback in a ref so the observer always has the latest version
  // This runs every render to keep the ref up-to-date
  loadMoreCallbackRef.current = loadMoreResults;

  // Setup infinite scroll observer
  useEffect(() => {
    if (!showResults || !results || !loadMoreTriggerRef.current) {
      console.log('Observer not set up:', { showResults, hasResults: !!results, hasTrigger: !!loadMoreTriggerRef.current });
      return;
    }

    // Check if there are more results to load
    const shouldObserve = selectedCategory === 'all'
      ? Object.values(hasMoreResults).some(v => v === true)
      : hasMoreResults[selectedCategory];

    if (!shouldObserve) {
      console.log('No more results to observe for', selectedCategory);
      return;
    }

    console.log('Setting up infinite scroll observer for', selectedCategory);

    const observerCallback = (entries) => {
      const [entry] = entries;
      if (entry.isIntersecting) {
        console.log('Intersection detected! Calling loadMoreResults');
        // Use the ref to always get the latest callback
        if (loadMoreCallbackRef.current) {
          loadMoreCallbackRef.current();
        }
      }
    };

    const observer = new IntersectionObserver(observerCallback, {
      root: resultsRef.current,
      threshold: 0.1
    });

    observer.observe(loadMoreTriggerRef.current);
    loadMoreObserverRef.current = observer;
    console.log('Observer attached successfully');

    return () => {
      console.log('Cleaning up observer');
      if (loadMoreObserverRef.current) {
        loadMoreObserverRef.current.disconnect();
      }
    };
  }, [showResults, results, hasMoreResults, selectedCategory]);

  // Handle input changes with debouncing
  const handleInputChange = (e) => {
    const newQuery = e.target.value;
    setQuery(newQuery);

    // Reset category limits and hasMoreResults when query changes
    setCategoryLimits({
      organizations: 5,
      signers: 5,
      units: 5,
      companies: 5,
      company_persons: 5,
      documents: 5,
      afm_entities: 5
    });

    setHasMoreResults({
      organizations: true,
      signers: true,
      units: true,
      companies: true,
      company_persons: true,
      documents: true,
      afm_entities: true
    });

    // Clear previous timeout
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }

    // Set new timeout for search
    searchTimeoutRef.current = setTimeout(() => {
      performSearch(newQuery);
    }, debounceMsRef.current); // SEARCH_DEBOUNCE_MS feature flag (default 300ms)
  };

  // Handle input focus
  const handleInputFocus = async () => {
    // If there are already results from a previous search, show them
    if (results && query.trim()) {
      setShowResults(true);
      return;
    }

    // If input is empty, fetch and show default suggestions + recently visited
    if (!query.trim()) {
      try {
        // Fetch both default suggestions and recently visited items in parallel
        const [defaultSuggestions, recentlyVisitedData] = await Promise.all([
          getDefaultSuggestions(10),
          getRecentlyVisited(5, true).catch(err => {
            console.warn('Failed to fetch recently visited:', err);
            return { visited: [], count: 0 };
          })
        ]);

        // Transform recently visited items into search result format
        const recentlyVisitedItems = recentlyVisitedData.visited?.map(item => ({
          id: item.selected_item_id,
          name: item.selected_item_name,
          title: item.selected_item_name,  // Used for display
          label: item.selected_item_name,
          type: item.entity_type,
          url: item.selected_item_url,
          timestamp: item.timestamp,  // Keep timestamp for sorting
          // Add a flag to style these differently if needed
          isRecentlyVisited: true
        })) || [];

        // Sort by timestamp (most recent first)
        recentlyVisitedItems.sort((a, b) => b.timestamp - a.timestamp);

        // Combine with default suggestions
        const combinedResults = {
          ...defaultSuggestions,
          results: {
            ...defaultSuggestions.results
          }
        };

        // Add recently visited as a separate category
        if (recentlyVisitedItems.length > 0) {
          combinedResults.results.recently_visited = recentlyVisitedItems;
          combinedResults.total_count += recentlyVisitedItems.length;
        }

        setResults(combinedResults);
        setShowResults(true);
      } catch (error) {
        console.error('Failed to fetch default suggestions:', error);
      }
    }
  };

  // Handle input blur (with delay to allow clicks)
  const handleInputBlur = (e) => {
    // Check if the click target is within the results container
    const relatedTarget = e.relatedTarget;
    if (relatedTarget && resultsRef.current?.contains(relatedTarget)) {
      // Don't hide results if clicking within results
      return;
    }

    setTimeout(() => {
      setShowResults(false);
      setSelectedIndex(-1);
    }, 150);
  };

  // Handle keyboard navigation
  const handleKeyDown = (e) => {
    if (!showResults || !results) return;

    const allItems = getAllSelectableItems();

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedIndex(prev =>
          prev < allItems.length - 1 ? prev + 1 : 0
        );
        break;

      case 'ArrowUp':
        e.preventDefault();
        setSelectedIndex(prev =>
          prev > 0 ? prev - 1 : allItems.length - 1
        );
        break;

      case 'Enter':
        e.preventDefault();
        if (selectedIndex >= 0 && allItems[selectedIndex]) {
          handleItemClick(allItems[selectedIndex]);
        }
        break;

      case 'Escape':
        setShowResults(false);
        setSelectedIndex(-1);
        inputRef.current?.blur();
        break;

      default:
        // Let other keys behave normally
        break;
    }
  };

  // Get all selectable items for keyboard navigation
  const getAllSelectableItems = () => {
    if (!results?.results) return [];

    const items = [];
    Object.entries(results.results).forEach(([category, categoryResults]) => {
      if (categoryResults && categoryResults.length > 0) {
        categoryResults.forEach(item => {
          items.push({ ...item, category });
        });
      }
    });

    return items;
  };

  // Handle item click
  const handleItemClick = (item) => {
    setShowResults(false);
    setSelectedIndex(-1);

    // Prepare tracking data
    let itemUrl = '';
    let itemName = item.name || item.title || item.label || '';

    // Determine URL based on item type
    switch (item.type) {
      case 'organization':
        itemUrl = `/entity/organization/${item.id}`;
        break;
      case 'signer':
        itemUrl = `/entity/signer/${item.id}`;
        break;
      case 'unit':
        itemUrl = `/entity/unit/${item.id}`;
        break;
      case 'company':
        itemUrl = `/entity/afm/${item.afm}`;
        break;
      case 'company_person':
        itemUrl = `/person/${encodeURIComponent(item.text || item.details?.person_name)}`;
        break;
      case 'afmentity':
        itemUrl = `/entity/afm/${item.details?.afm}`;
        break;
      case 'document':
        itemUrl = `/decision/${item.details?.decision_id}`;
        itemName = item.subject || item.description || itemName;
        break;
      default:
        break;
    }

    // Track the selection (fire and forget - don't wait for response)
    if (query && item.type && item.id) {
      trackSearchSelection(query, item.type, item.id, itemName, itemUrl).catch(err => {
        // Silently fail - tracking shouldn't break UX
        console.debug('Selection tracking failed:', err);
      });
    }

    // Call custom handler if provided
    if (onResultClick) {
      onResultClick(item);
      return;
    }

    // Default navigation logic
    switch (item.type) {
      case 'organization':
        navigate(`/entity/organization/${item.id}`);
        break;
      case 'signer':
        navigate(`/entity/signer/${item.id}`);
        break;
      case 'unit':
        navigate(`/entity/unit/${item.id}`);
        break;
      case 'company':
        // #TODO: Α separate company_person page showing companies they are associated with with their roles and also amounts per amountype
        navigate(`/entity/afm/${item.afm}`);
        break;
      case 'company_person':
        navigate(`/person/${encodeURIComponent(item.text || item.details?.person_name)}`);
        break;
      case 'afmentity':
        navigate(`/entity/afm/${item.details?.afm}`);
        break;
      case 'document':
        navigate(`/decision/${item.details.decision_id}`);
        break;
      default:
        console.warn(`Unknown item type: ${item.type}`);
    }
  };

  // Handle clear button
  const handleClear = () => {
    setQuery('');
    setResults(null);
    setShowResults(false);
    setSelectedIndex(-1);
    inputRef.current?.focus();
  };

  // Handle delete single history item
  const handleDeleteHistoryItem = async (e, item) => {
    e.stopPropagation(); // Prevent triggering item click

    if (!item.timestamp) {
      console.error('No timestamp found for history item');
      return;
    }

    try {
      await deleteSingleHistoryItem(item.timestamp);

      // Remove the item from the results
      if (results?.results?.recently_visited) {
        const newResults = { ...results };
        newResults.results.recently_visited = newResults.results.recently_visited.filter(
          i => i.timestamp !== item.timestamp
        );
        newResults.total_count -= 1;

        // If no more recently visited items, remove the category
        if (newResults.results.recently_visited.length === 0) {
          delete newResults.results.recently_visited;
          if (selectedCategory === 'recently_visited') {
            setSelectedCategory('all');
          }
        }

        setResults(newResults);
      }
    } catch (error) {
      console.error('Failed to delete history item:', error);
    }
  };

  // Handle clear history with confirmation
  const handleClearHistory = async () => {
    // Show confirmation dialog
    const confirmed = window.confirm(
      'Are you sure you want to clear all your search history? This action cannot be undone.'
    );

    if (!confirmed) {
      return;
    }

    try {
      await clearSearchHistory();
      // Remove recently_visited from results
      if (results?.results?.recently_visited) {
        const newResults = { ...results };
        newResults.total_count -= newResults.results.recently_visited.length;
        delete newResults.results.recently_visited;
        setResults(newResults);
        // Switch to 'all' if we were on 'recently_visited'
        if (selectedCategory === 'recently_visited') {
          setSelectedCategory('all');
        }
      }
    } catch (error) {
      console.error('Failed to clear history:', error);
    }
  };

  // Handle view all results
  const handleViewAll = () => {
    setShowResults(false);
    // Navigate to a full search results page
    navigate(`/search?q=${encodeURIComponent(query)}`);
  };



  // Render highlights in text
  const renderHighlightedText = (text) => {
    if (!text) return '';

    // Text might already contain HTML tags from the API
    return <span dangerouslySetInnerHTML={{ __html: text }} />;
  };

  // Render document excerpt with highlights
  const renderDocumentExcerpt = (item) => {
    if (item.highlights?.content) {
      return (
        <div className="super-search-document-excerpt">
          {item.highlights.content.slice(0, 2).map((excerpt, index) => (
            <div key={index} dangerouslySetInnerHTML={{ __html: excerpt }} />
          ))}
        </div>
      );
    }

    if (item.description) {
      return (
        <div className="super-search-document-excerpt">
          <span dangerouslySetInnerHTML={{ __html: item.description }} />
        </div>
      );
    }

    return null;
  };

  // Render document metadata
  const renderDocumentMetadata = (item) => {
    if (!item.details) return null;

    const metadata = [];

    if (item.details.issue_date) {
      metadata.push({
        icon: '📅',
        text: new Date(item.details.issue_date).toLocaleDateString()
      });
    }

    if (item.details.amount && item.details.currency) {
      metadata.push({
        icon: '💰',
        text: `${item.details.amount} ${item.details.currency}`
      });
    }

    if (item.details.signers?.length > 0) {
      metadata.push({
        icon: '✍️',
        text: item.details.signers.join(', ')
      });
    }

    if (metadata.length === 0) return null;

    return (
      <div className="super-search-document-metadata">
        {metadata.map((meta, index) => (
          <div key={index} className="super-search-document-metadata-item">
            <span>{meta.icon}</span>
            <span>{meta.text}</span>
          </div>
        ))}
      </div>
    );
  };

  const allItems = getAllSelectableItems();

  return (
    <div className={`super-search-container ${className}`}>
      <div className="super-search-input-wrapper">
        <SearchIcon size={18} className="super-search-icon" />
        <input
          ref={inputRef}
          type="text"
          className="super-search-input"
          placeholder={placeholder}
          value={query}
          onChange={handleInputChange}
          onFocus={handleInputFocus}
          onBlur={handleInputBlur}
          onKeyDown={handleKeyDown}
          autoComplete="off"
        />
        {isLoading && (
          <div className="super-search-loading">
            <div className="super-search-loading-spinner" />
          </div>
        )}
        {!isLoading && documentsLoading && (
          <div className="super-search-loading" title="Loading documents...">
            <div className="super-search-loading-spinner" />
          </div>
        )}
        {query && !isLoading && (
          <button
            className="super-search-clear"
            onClick={handleClear}
            type="button"
            aria-label="Clear search"
          >
            ✕
          </button>
        )}
      </div>

      {showResults && (
        <div ref={resultsRef} className="super-search-results">
          {!results || results.total_count === 0 ? (
            <div className="super-search-no-results">
              No results found for "{query}"
            </div>
          ) : (
            <>
              {/* Category Tabs */}
              <CategoryTabs
                className="super-search-tabs"
                categories={(() => {
                  const tabs = [
                    { key: 'all', label: 'All Results', count: results.total_count },
                  ];

                  // Recently Visited
                  if (results.results.recently_visited?.length > 0) {
                    tabs.push({
                      key: 'recently_visited',
                      label: 'Recently Visited',
                      icon: <TimerIcon size={14} />,
                      count: results.results.recently_visited.length,
                      actionSlot: (
                        <button
                          className="super-search-clear-history"
                          onClick={handleClearHistory}
                          onMouseDown={(e) => e.preventDefault()}
                          title="Clear all history"
                        >
                          <TrashIcon size={12} />
                        </button>
                      ),
                    });
                  }

                  // All other categories with results
                  const categoryKeys = [
                    'organizations', 'signers', 'units', 'companies',
                    'company_persons', 'afm_entities', 'documents',
                  ];
                  categoryKeys.forEach((key) => {
                    const items = results.results[key];
                    if (items?.length > 0) {
                      tabs.push({
                        key,
                        label: getCategoryLabel(key),
                        icon: getCategoryIcon(key, 14),
                        count: items.length,
                      });
                    }
                  });

                  return tabs;
                })()}
                selectedKey={selectedCategory}
                onSelect={setSelectedCategory}
              />

              {Object.entries(results.results)
                .filter(([category]) => {
                  // If 'all' is selected, show all categories
                  // Otherwise, only show the selected category
                  return selectedCategory === 'all' || category === selectedCategory;
                })
                .map(([category, categoryResults]) => {
                if (!categoryResults || categoryResults.length === 0) return null;

                return (
                  <div key={category} className="super-search-category">
                    <div className="super-search-category-header">
                      <span className="super-search-category-icon">
                        {category === 'recently_visited' ? (
                          <TimerIcon size={16} />
                        ) : (
                          getCategoryIcon(categoryResults[0]?.type, 16)
                        )}
                      </span>
                      <span>{getCategoryLabel(category)}</span>
                      <span className="super-search-category-count">
                        {categoryResults.length}
                      </span>
                    </div>

                    {categoryResults.map((item, index) => {
                      const globalIndex = allItems.findIndex(
                        globalItem => globalItem.id === item.id && globalItem.type === item.type
                      );
                      const isSelected = globalIndex === selectedIndex;
                      const isDocument = item.type === 'document';
                      const isRecentlyVisitedCategory = category === 'recently_visited';

                      return (
                        <div
                          key={`${item.type}-${item.id}`}
                          className={`super-search-item ${isDocument ? 'super-search-document-item' : ''} ${isSelected ? 'selected' : ''} ${item.isRecentlyVisited ? 'recently-visited' : ''}`}
                          onClick={() => handleItemClick(item)}
                          onMouseEnter={() => setSelectedIndex(globalIndex)}
                          style={{
                            backgroundColor: isSelected ? 'var(--hover-bg)' : 'transparent'
                          }}
                        >
                          <div className="super-search-item-icon">
                            {getCategoryIcon(item.type, 16)}
                          </div>

                          <div className="super-search-item-content">
                            <div className="super-search-item-title">
                              {item.isRecentlyVisited && category !== 'recently_visited' && (
                                <span className="recently-visited-badge" title="Recently Visited">
                                  <TimerIcon size={14} />
                                </span>
                              )}
                              {renderHighlightedText(item.title)}
                            </div>

                            {item.subtitle && (
                              <div className="super-search-item-subtitle">
                                {item.subtitle}
                              </div>
                            )}

                            {item.description && !isDocument && (
                              <div className="super-search-item-description">
                                {item.description}
                              </div>
                            )}

                            {isDocument && renderDocumentExcerpt(item)}
                            {isDocument && renderDocumentMetadata(item)}
                          </div>

                          {/* Delete button for Recently Visited items */}
                          {isRecentlyVisitedCategory && (
                            <button
                              className="super-search-item-delete"
                              onClick={(e) => handleDeleteHistoryItem(e, item)}
                              onMouseDown={(e) => e.preventDefault()}
                              title="Remove from history"
                            >
                              <TrashIcon size={14} />
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                );
              })}

              {results.total_count > allItems.length && (
                <button
                  className="super-search-view-all"
                  onClick={handleViewAll}
                  onMouseDown={(e) => e.preventDefault()}
                >
                  View all {results.total_count} results
                </button>
              )}

              {/* Show loading indicator when fetching more */}
              {isLoading && (
                <div className="super-search-loading-more">
                  <div className="super-search-loading-spinner" />
                  <span>Loading more results...</span>
                </div>
              )}

              {/* Show "No more results" when infinite scroll has ended */}
              {(() => {
                const noMoreResults = selectedCategory === 'all'
                  ? Object.values(hasMoreResults).every(v => v === false)
                  : hasMoreResults[selectedCategory] === false;

                return noMoreResults && !isLoading && (
                  <div className="super-search-no-more-results">
                    No more results
                  </div>
                );
              })()}

              {/* Infinite scroll trigger */}
              <div
                ref={loadMoreTriggerRef}
                className="super-search-load-more-trigger"
              />
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default SuperSearch;
