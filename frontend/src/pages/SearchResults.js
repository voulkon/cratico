import React, { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { getFullSearchResults } from '../api/searchApi';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import SuperSearch from '../components/SuperSearch';
import './SearchResults.css';

const SearchResults = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const [results, setResults] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const query = searchParams.get('q') || '';
  useDocumentTitle(query ? `Search: ${query}` : 'Search');

  // Perform search when query changes
  useEffect(() => {
    if (query.trim()) {
      performSearch(query);
    } else {
      setResults(null);
    }
  }, [query]);

  const performSearch = async (searchQuery) => {
    setIsLoading(true);
    setError(null);

    try {
      const searchResults = await getFullSearchResults(searchQuery, 20);
      setResults(searchResults);
    } catch (err) {
      console.error('Search failed:', err);
      setError('Failed to perform search. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleNewSearch = (newQuery) => {
    setSearchParams({ q: newQuery });
  };

  const handleResultClick = (item) => {
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
        // navigate(`/entity/company/${item.id}`);
        navigate(`/entity/afm/${item.afm}`);
        break;
      case 'company_person':
        navigate(`/person/${encodeURIComponent(item.text || item.details?.person_name)}`);
        break;
      case 'document':
        navigate(`/decision/${item.details.decision_id}`);
        break;
      default:
        console.warn(`Unknown item type: ${item.type}`);
    }
  };

  const getItemIcon = (type) => {
    const icons = {
      organization: '🏢',
      signer: '👤',
      unit: '🏛️',
      company: '🏪',
      company_person: '👨‍💼',
      document: '📄'
    };
    return icons[type] || '📋';
  };

  const getCategoryName = (category) => {
    const names = {
      organizations: 'Organizations',
      signers: 'Signers',
      units: 'Units',
      companies: 'Companies',
      company_persons: 'Company Persons',
      documents: 'Documents'
    };
    return names[category] || category;
  };

  const renderHighlightedText = (text) => {
    if (!text) return '';
    return <span dangerouslySetInnerHTML={{ __html: text }} />;
  };

  const renderDocumentExcerpt = (item) => {
    if (item.highlights?.content) {
      return (
        <div className="search-results-document-excerpt">
          {item.highlights.content.slice(0, 3).map((excerpt, index) => (
            <div key={index} dangerouslySetInnerHTML={{ __html: excerpt }} />
          ))}
        </div>
      );
    }

    if (item.description) {
      return (
        <div className="search-results-document-excerpt">
          <span dangerouslySetInnerHTML={{ __html: item.description }} />
        </div>
      );
    }

    return null;
  };

  const renderDocumentMetadata = (item) => {
    if (!item.details) return null;

    const metadata = [];

    if (item.details.issue_date) {
      metadata.push({
        icon: '📅',
        label: 'Date',
        text: new Date(item.details.issue_date).toLocaleDateString()
      });
    }

    if (item.details.amount && item.details.currency) {
      metadata.push({
        icon: '💰',
        label: 'Amount',
        text: `${item.details.amount} ${item.details.currency}`
      });
    }

    if (item.details.signers?.length > 0) {
      metadata.push({
        icon: '✍️',
        label: 'Signers',
        text: item.details.signers.join(', ')
      });
    }

    if (item.details.ada) {
      metadata.push({
        icon: '🔗',
        label: 'ADA',
        text: item.details.ada
      });
    }

    if (metadata.length === 0) return null;

    return (
      <div className="search-results-document-metadata">
        {metadata.map((meta, index) => (
          <div key={index} className="search-results-metadata-item">
            <span className="search-results-metadata-icon">{meta.icon}</span>
            <span className="search-results-metadata-label">{meta.label}:</span>
            <span className="search-results-metadata-text">{meta.text}</span>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="search-results-page">
      <div className="search-results-header">
        <div className="search-results-search-container">
          <SuperSearch
            placeholder="Search organizations, documents, companies..."
            showFullResults={false}
            onResultClick={(item) => {
              // Update URL and trigger search
              handleNewSearch(item.text || item.title);
            }}
            className="search-results-search"
          />
        </div>

        {query && (
          <div className="search-results-query-info">
            <h1>Search Results for "{query}"</h1>
            {results && (
              <p className="search-results-count">
                {results.total_count} result{results.total_count !== 1 ? 's' : ''} found
              </p>
            )}
          </div>
        )}
      </div>

      <div className="search-results-content">
        {isLoading && (
          <div className="search-results-loading">
            <div className="search-results-loading-spinner" />
            <p>Searching...</p>
          </div>
        )}

        {error && (
          <div className="search-results-error">
            <h2>Search Error</h2>
            <p>{error}</p>
            <button
              onClick={() => performSearch(query)}
              className="search-results-retry-btn"
            >
              Try Again
            </button>
          </div>
        )}

        {!isLoading && !error && results && results.total_count === 0 && (
          <div className="search-results-no-results">
            <h2>No Results Found</h2>
            <p>Try different keywords or check your spelling.</p>
          </div>
        )}

        {!isLoading && !error && results && results.total_count > 0 && (
          <div className="search-results-categories">
            {Object.entries(results.results).map(([category, categoryResults]) => {
              if (!categoryResults || categoryResults.length === 0) return null;

              return (
                <div key={category} className="search-results-category">
                  <h2 className="search-results-category-title">
                    <span className="search-results-category-icon">
                      {getItemIcon(categoryResults[0]?.type)}
                    </span>
                    {getCategoryName(category)}
                    <span className="search-results-category-count">
                      ({categoryResults.length})
                    </span>
                  </h2>

                  <div className="search-results-items">
                    {categoryResults.map((item) => {
                      const isDocument = item.type === 'document';

                      return (
                        <div
                          key={`${item.type}-${item.id}`}
                          className={`search-results-item ${isDocument ? 'search-results-document-item' : ''}`}
                          onClick={() => handleResultClick(item)}
                        >
                          <div className="search-results-item-icon">
                            {getItemIcon(item.type)}
                          </div>

                          <div className="search-results-item-content">
                            <div className="search-results-item-title">
                              {renderHighlightedText(item.title)}
                            </div>

                            {item.subtitle && (
                              <div className="search-results-item-subtitle">
                                {item.subtitle}
                              </div>
                            )}

                            {item.description && !isDocument && (
                              <div className="search-results-item-description">
                                {item.description}
                              </div>
                            )}

                            {isDocument && renderDocumentExcerpt(item)}
                            {isDocument && renderDocumentMetadata(item)}

                            {item.search_score && (
                              <div className="search-results-item-score">
                                Relevance: {item.search_score.toFixed(2)}
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export default SearchResults;
