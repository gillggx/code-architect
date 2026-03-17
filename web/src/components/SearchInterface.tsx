/**
 * Search Interface component
 * 
 * Semantic search interface for querying
 * project patterns and code
 */

import React, { useState } from 'react';
import apiClient from '../api/client';
import { useSearch } from '../store/app';

/**
 * Search Interface component
 */
const SearchInterface: React.FC = () => {
  const [searchInput, setSearchInput] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const { query, results, error, setQuery, setResults, setError } = useSearch();

  /**
   * Handle search submission
   */
  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!searchInput.trim()) {
      setError('Please enter a search query');
      return;
    }

    try {
      setIsSearching(true);
      setError(null);
      setQuery(searchInput);

      const response = await apiClient.search({
        query: searchInput,
        top_k: 10,
        include_patterns: true,
        confidence_threshold: 0.5,
      });

      setResults(response.results);
    } catch (err) {
      const error = err as any;
      setError(error.message || 'Search failed');
    } finally {
      setIsSearching(false);
    }
  };

  return (
    <div className="search-interface">
      <h2>Search Projects</h2>

      {/* Search form */}
      <form onSubmit={handleSearch} className="search-form card">
        <div className="input-group">
          <label htmlFor="searchQuery">Search Query</label>
          <input
            id="searchQuery"
            type="text"
            placeholder="Search for patterns, code, or concepts..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            disabled={isSearching}
          />
        </div>

        {error && <div className="error-message">{error}</div>}

        <button
          type="submit"
          disabled={isSearching}
          className="btn btn-primary"
        >
          {isSearching ? (
            <>
              <span className="spinner small"></span> Searching...
            </>
          ) : (
            <>🔎 Search</>
          )}
        </button>
      </form>

      {/* Results display */}
      {query && (
        <div className="search-results card">
          <h3>
            Results for "{query}" ({results.length} found)
          </h3>

          {results.length === 0 ? (
            <p className="no-results">No results found for your search</p>
          ) : (
            <div className="results-list">
              {results.map((result, idx) => (
                <div key={result.id} className="result-item">
                  <div className="result-header">
                    <h4>{result.title}</h4>
                    <span className="result-type">{result.type}</span>
                    <span className="result-confidence">
                      {(result.confidence * 100).toFixed(0)}%
                    </span>
                  </div>

                  <p className="result-content">{result.content}</p>

                  {result.location && (
                    <small className="result-location">
                      📍 {result.location.file}:{result.location.line}
                    </small>
                  )}

                  <small className="result-source">
                    Source: {result.source}
                  </small>
                </div>
              ))}
            </div>
          )}

          {results.length > 0 && (
            <div className="search-stats">
              <small>
                Showing {results.length} results for "{query}"
              </small>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default SearchInterface;
