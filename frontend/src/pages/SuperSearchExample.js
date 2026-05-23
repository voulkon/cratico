import React from 'react';
import SuperSearch from '../components/SuperSearch';
import './SuperSearchExample.css';

const SuperSearchExample = () => {
  const handleResultClick = (item) => {
    console.log('Clicked on:', item);
    // You can customize what happens when a result is clicked
    alert(`You clicked on: ${item.title || item.text} (${item.type})`);
  };

  return (
    <div className="super-search-example">
      <div className="example-container">
        <h1>Super Search Examples</h1>
        <p>Try searching for Greek terms like "ΚΑΡΤΑ ΣΗΜΑΝΣΗΣ", "ΚΟΙΝΟΠΡΑΞΙΑ ΠΛΟΙΩΝ", or "ΟΡΓΑΝΙΣΜΟΣ ΤΗΛΕΠΙΚΟΙΝΩΝΙΩΝ"</p>

        {/* Basic search with full results */}
        <section className="example-section">
          <h2>Full Search with Documents</h2>
          <SuperSearch
            placeholder="Search organizations, documents, companies..."
            showFullResults={true}
            onResultClick={handleResultClick}
          />
        </section>

        {/* Autocomplete-style search */}
        <section className="example-section">
          <h2>Quick Autocomplete (No Documents)</h2>
          <SuperSearch
            placeholder="Quick search for entities only..."
            showFullResults={false}
            onResultClick={handleResultClick}
          />
        </section>

        {/* Custom placeholder */}
        <section className="example-section">
          <h2>Custom Search</h2>
          <SuperSearch
            placeholder="Search for Greek government data..."
            showFullResults={true}
            autoFocus={false}
            className="custom-search"
          />
        </section>
      </div>
    </div>
  );
};

export default SuperSearchExample;
