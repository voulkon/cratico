import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getPublicFolder } from '../api/bookmarks';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import {
  ExternalLink,
  Share2,
  Loader2,
  AlertTriangle,
  FolderOpen,
  Star,
  Copy,
} from 'lucide-react';
import './SharedPages.css';

/**
 * Publicly accessible page for a shared folder and its bookmarks.
 * No authentication required.
 */
export default function SharedFolderPage() {
  const { slug } = useParams();
  const [folderData, setFolderData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  useDocumentTitle(folderData ? folderData.folder.name : 'Shared Folder');

  useEffect(() => {
    if (!slug) return;
    setLoading(true);
    setError(null);
    getPublicFolder(slug)
      .then((data) => {
        setFolderData(data);
        setLoading(false);
      })
      .catch((err) => {
        if (err.response?.status === 404) {
          setError('This shared folder does not exist or is no longer public.');
        } else {
          setError('Failed to load the shared folder. Please try again later.');
        }
        setLoading(false);
      });
  }, [slug]);

  if (loading) {
    return (
      <div className="shared-page shared-loading">
        <Loader2 size={32} className="shared-spinner" />
        <p>Loading shared folder…</p>
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

  if (!folderData) return null;

  const { folder, bookmarks } = folderData;
  const shareUrl = window.location.href;

  async function handleCopyLink() {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const input = document.createElement('input');
      input.value = shareUrl;
      document.body.appendChild(input);
      input.select();
      document.execCommand('copy');
      document.body.removeChild(input);
    }
  }

  return (
    <div className="shared-page shared-folder-page">
      <div className="shared-folder-card">
        {/* Folder header */}
        <div className="shared-folder-header">
          <div className="shared-header">
            <Share2 size={20} className="shared-icon" />
            <span className="shared-badge">Shared Folder</span>
          </div>

          <div className="shared-folder-title-row">
            <span
              className="shared-folder-color-dot"
              style={{ backgroundColor: folder.color || '#3b82f6' }}
            />
            <h1 className="shared-title">
              {folder.icon && <span className="shared-folder-icon">{folder.icon}</span>}
              {folder.name}
            </h1>
          </div>

          {folder.description && (
            <p className="shared-description">{folder.description}</p>
          )}

          <div className="shared-meta">
            <span>
              <FolderOpen size={14} /> {folder.bookmark_count} bookmark{folder.bookmark_count !== 1 ? 's' : ''}
            </span>
            {folder.shared_by && (
              <span className="shared-by">Shared by {folder.shared_by}</span>
            )}
          </div>

          <div className="shared-actions">
            <button className="shared-copy-btn" onClick={handleCopyLink}>
              <Copy size={16} />
              {copied ? 'Copied!' : 'Copy Link'}
            </button>
          </div>
        </div>

        {/* Bookmarks list */}
        <div className="shared-bookmarks-list">
          {bookmarks.length === 0 ? (
            <p className="shared-empty">This folder has no bookmarks yet.</p>
          ) : (
            bookmarks.map((b) => (
              <a
                key={b.id}
                href={b.url}
                className="shared-bookmark-item"
                target="_blank"
                rel="noopener noreferrer"
              >
                <div className="shared-bookmark-item-content">
                  <div className="shared-bookmark-item-header">
                    {b.is_favorite && (
                      <Star size={14} className="shared-star" fill="currentColor" />
                    )}
                    <span className="shared-bookmark-title">{b.title}</span>
                  </div>
                  {b.notes && (
                    <p className="shared-bookmark-notes">{b.notes}</p>
                  )}
                  <div className="shared-bookmark-meta">
                    {b.view_type && (
                      <span className="shared-view-type">{b.view_type}</span>
                    )}
                    <span className="shared-bookmark-url">{b.url}</span>
                  </div>
                </div>
                <ExternalLink size={16} className="shared-bookmark-external" />
              </a>
            ))
          )}
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
