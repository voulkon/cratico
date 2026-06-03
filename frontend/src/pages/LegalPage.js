import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import apiClient from '../api/client';
import { useTranslation } from '../contexts/TranslationContext';
import './LegalPage.css';

/**
 * LegalPage - Renders a single legal document fetched by type slug.
 *
 * Route: /legal/:type
 * Fetches the markdown content from GET /api/system/legal/?type=:type&language=:lang
 * and renders it using react-markdown with GFM support.
 */
const LegalPage = () => {
  const { type } = useParams();
  const { language } = useTranslation();
  const [doc, setDoc] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);

    apiClient
      .get(`/system/legal/?type=${encodeURIComponent(type)}&language=${language}`)
      .then((res) => {
        setDoc(res.data);
        setLoading(false);
      })
      .catch((err) => {
        if (err.response?.status === 404) {
          setError('Document not found');
        } else {
          setError('Failed to load document');
        }
        setLoading(false);
      });
  }, [type, language]);

  if (loading) {
    return (
      <div className="legal-page">
        <div className="legal-loading">Loading...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="legal-page">
        <div className="legal-error">
          <h2>{error}</h2>
          <Link to="/" className="legal-back-link">
            ← Back to Home
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="legal-page">
      <article className="legal-content">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {doc.content}
        </ReactMarkdown>
      </article>
      {doc.updated_at && (
        <div className="legal-updated">
          Last updated: {new Date(doc.updated_at).toLocaleDateString()}
        </div>
      )}
    </div>
  );
};

export default LegalPage;
