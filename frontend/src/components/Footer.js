import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import apiClient from '../api/client';
import './Footer.css';

/**
 * Footer - Site footer with dynamically loaded legal links.
 *
 * Fetches available legal document types from the API and renders
 * them as links.  Add a new document in Django admin and it appears
 * here automatically — no frontend changes needed.
 */
const Footer = () => {
  const [docs, setDocs] = useState([]);
  const [error, setError] = useState(false);

  useEffect(() => {
    apiClient
      .get('/system/legal/')
      .then((res) => setDocs(res.data))
      .catch(() => setError(true));
  }, []);

  // Don't render anything if there are no documents or the request failed
  if (error || !docs.length) return null;

  return (
    <footer className="site-footer">
      <div className="footer-content">
        <div className="footer-links">
          {docs.map((doc) => (
            <Link
              key={doc.type}
              to={`/legal/${doc.type}`}
              className="footer-link"
            >
              {doc.title}
            </Link>
          ))}
        </div>
        <div className="footer-brand">
          <span>Crati</span>
        </div>
      </div>
    </footer>
  );
};

export default Footer;
