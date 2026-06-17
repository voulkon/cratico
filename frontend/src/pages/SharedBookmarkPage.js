import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getPublicBookmark } from '../api/bookmarks';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { ExternalLink, Share2, Loader2, AlertTriangle } from 'lucide-react';
import './SharedPages.css';

/**
 * Publicly accessible page for a shared bookmark.
 * No authentication required.
 */
export default function SharedBookmarkPage() {
  const { slug } = useParams();
  const [bookmark, setBookmark] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useDocumentTitle(bookmark ? bookmark.title : 'Shared Bookmark');

  useEffect(() => {
    if (!slug) return;
    setLoading(true);
    setError(null);
    getPublicBookmark(slug)
      .then((data) => {
        setBookmark(data);
        setLoading(false);
      })
      .catch((err) => {
        if (err.response?.status === 404) {
          setError('This shared bookmark does not exist or is no longer public.');
        } else {
          setError('Failed to load the shared bookmark. Please try again later.');
        }
        setLoading(false);
      });
  }, [slug]);

  if (loading) {
    return (
      <div className="shared-page shared-loading">
        <Loader2 size={32} className="shared-spinner" />
        <p>Loading shared bookmark…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="shared-page shared-error">
        <div className="shared-error-card">
          <AlertTriangle size={48} className="shared-error-icon" />
          <h1>Not Found</h1>
          <p>{error}</p>
          <Link to="/" className="shared-home-link">Go to Crati</Link>
        </div>
      </div>
    );
  }

  if (!bookmark) return null;

  const shareUrl = window.location.href;

  async function handleCopyLink() {
    try {
      await navigator.clipboard.writeText(shareUrl);
    } catch {
      // Fallback
      const input = document.createElement('input');
      input.value = shareUrl;
      document.body.appendChild(input);
      input.select();
      document.execCommand('copy');
      document.body.removeChild(input);
    }
  }

  return (
    <div className="shared-page">
      <div className="shared-card">
        <div className="shared-header">
          <Share2 size={20} className="shared-icon" />
          <span className="shared-badge">Shared Bookmark</span>
        </div>

        <h1 className="shared-title">{bookmark.title}</h1>

        {bookmark.notes && (
          <p className="shared-notes">{bookmark.notes}</p>
        )}

        <div className="shared-meta">
          {bookmark.view_type && (
            <span className="shared-view-type">{bookmark.view_type}</span>
          )}
          {bookmark.shared_by && (
            <span className="shared-by">Shared by {bookmark.shared_by}</span>
          )}
        </div>

        <div className="shared-actions">
          <a
            href={bookmark.url}
            className="shared-open-btn"
            target="_blank"
            rel="noopener noreferrer"
          >
            <ExternalLink size={18} />
            Open Bookmark
          </a>
          <button className="shared-copy-btn" onClick={handleCopyLink}>
            Copy Link
          </button>
        </div>

        <div className="shared-footer">
          <Link to="/" className="shared-powered-by">
            Powered by Crati
          </Link>
        </div>
      </div>
    </div>
  );
}
