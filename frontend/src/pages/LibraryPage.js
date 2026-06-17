import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Folder,
  Star,
  BookOpen,
  Clock,
  Edit2,
  Trash2,
  FileText,
  X,
  Eye,
  ArrowRight,
  Plus,
  Share2
} from 'lucide-react';
import {
  getBookmarks,
  getFolders,
  createFolder,
  updateFolder,
  deleteFolder,
  updateBookmark,
  deleteBookmark,
  toggleBookmarkPublic,
  toggleFolderPublic
} from '../api/bookmarks';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import './LibraryPage.css';

/**
 * Library Page - Full-featured bookmark and folder management
 * Layout: Folders (left) | Bookmarks (center) | Details (right)
 */
export default function LibraryPage() {
  useDocumentTitle('Library');
  const navigate = useNavigate();

  // State
  const [folders, setFolders] = useState([]);
  const [bookmarks, setBookmarks] = useState([]);
  const [selectedFolder, setSelectedFolder] = useState(null);
  const [selectedBookmark, setSelectedBookmark] = useState(null);
  const [viewMode, setViewMode] = useState('all'); // 'all', 'favorites', 'recent'
  const [isLoading, setIsLoading] = useState(true);
  const [shareFeedback, setShareFeedback] = useState(null); // { id, type, slug }

  // Clear share feedback after 3s
  useEffect(() => {
    if (shareFeedback) {
      const timer = setTimeout(() => setShareFeedback(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [shareFeedback]);

  // Modal states
  const [showFolderModal, setShowFolderModal] = useState(false);
  const [editingFolder, setEditingFolder] = useState(null);
  const [folderFormData, setFolderFormData] = useState({
    name: '',
    description: '',
    color: '',
    icon: ''
  });

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    loadBookmarks();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedFolder, viewMode]);

  async function loadData() {
    setIsLoading(true);
    try {
      const [foldersData, bookmarksData] = await Promise.all([
        getFolders(),
        getBookmarks()
      ]);
      setFolders(foldersData);
      setBookmarks(bookmarksData);
    } catch (error) {
      console.error('Failed to load data:', error);
    } finally {
      setIsLoading(false);
    }
  }

  async function loadBookmarks() {
    try {
      const params = {};
      if (selectedFolder) {
        params.folder = selectedFolder.id;
      }
      if (viewMode === 'favorites') {
        params.favorites = 'true';
      }
      const data = await getBookmarks(params);

      // Sort by recent if in recent mode
      if (viewMode === 'recent') {
        data.sort((a, b) => new Date(b.last_visited || b.updated_at) - new Date(a.last_visited || a.updated_at));
      }

      setBookmarks(data);
    } catch (error) {
      console.error('Failed to load bookmarks:', error);
    }
  }

  function handleFolderClick(folder) {
    setSelectedFolder(folder?.id === selectedFolder?.id ? null : folder);
    setSelectedBookmark(null);
  }

  function handleBookmarkClick(bookmark) {
    setSelectedBookmark(bookmark);
  }

  function handleNavigateToBookmark(bookmark) {
    navigate(bookmark.url);
  }

  async function handleToggleFavorite(bookmark) {
    try {
      await updateBookmark(bookmark.id, { is_favorite: !bookmark.is_favorite });
      loadBookmarks();
      if (selectedBookmark?.id === bookmark.id) {
        setSelectedBookmark({ ...bookmark, is_favorite: !bookmark.is_favorite });
      }
    } catch (error) {
      console.error('Failed to toggle favorite:', error);
    }
  }

  async function handleDeleteBookmark(bookmarkId) {
    if (!window.confirm('Delete this bookmark?')) return;
    try {
      await deleteBookmark(bookmarkId);
      loadBookmarks();
      if (selectedBookmark?.id === bookmarkId) {
        setSelectedBookmark(null);
      }
    } catch (error) {
      console.error('Failed to delete bookmark:', error);
    }
  }

  function openFolderModal(folder = null) {
    setEditingFolder(folder);
    setFolderFormData(folder || {
      name: '',
      description: '',
      color: '',
      icon: ''
    });
    setShowFolderModal(true);
  }

  async function handleSaveFolder() {
    try {
      if (editingFolder) {
        await updateFolder(editingFolder.id, folderFormData);
      } else {
        await createFolder(folderFormData);
      }
      setShowFolderModal(false);
      loadData();
    } catch (error) {
      console.error('Failed to save folder:', error);
      alert('Failed to save folder: ' + error.message);
    }
  }

  async function handleDeleteFolder(folderId) {
    if (!window.confirm('Delete this folder? Bookmarks will be moved to root.')) return;
    try {
      await deleteFolder(folderId);
      if (selectedFolder?.id === folderId) {
        setSelectedFolder(null);
      }
      loadData();
    } catch (error) {
      console.error('Failed to delete folder:', error);
    }
  }

  // ── Share handlers ─────────────────────────────────────────────

  async function copyShareUrl(url) {
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      const input = document.createElement('input');
      input.value = url;
      document.body.appendChild(input);
      input.select();
      document.execCommand('copy');
      document.body.removeChild(input);
    }
  }

  async function handleToggleBookmarkShare(bookmark, e) {
    e.stopPropagation();
    try {
      const makePublic = !bookmark.is_public;
      const updated = await toggleBookmarkPublic(bookmark.id, makePublic);
      if (makePublic && updated?.public_slug) {
        const url = `${window.location.origin}/share/bookmark/${updated.public_slug}`;
        await copyShareUrl(url);
        setShareFeedback({ id: bookmark.id, type: 'bookmark', slug: updated.public_slug });
      } else {
        setShareFeedback(null);
      }
      loadBookmarks();
      if (selectedBookmark?.id === bookmark.id) {
        setSelectedBookmark(updated || { ...bookmark, is_public: makePublic });
      }
    } catch (error) {
      console.error('Failed to toggle bookmark share:', error);
    }
  }

  async function handleToggleFolderShare(folder, e) {
    e.stopPropagation();
    try {
      const makePublic = !folder.is_public;
      const updated = await toggleFolderPublic(folder.id, makePublic);
      if (makePublic && updated?.public_slug) {
        const url = `${window.location.origin}/share/folder/${updated.public_slug}`;
        await copyShareUrl(url);
        setShareFeedback({ id: folder.id, type: 'folder', slug: updated.public_slug });
      } else {
        setShareFeedback(null);
      }
      loadData();
    } catch (error) {
      console.error('Failed to toggle folder share:', error);
    }
  }

  if (isLoading) {
    return (
      <div className="library-loading">
        <div className="library-loading-spinner"></div>
        <div>Loading your library...</div>
      </div>
    );
  }

  return (
    <div className="library-page">
      {/* LEFT: Folders Sidebar */}
      <div className="library-folders-sidebar">
        <div className="library-sidebar-header">
          <h2 className="library-sidebar-title">Folders</h2>
          <button
            onClick={() => openFolderModal()}
            className="library-new-folder-btn"
          >
            <Plus size={16} />
            New
          </button>
        </div>

        {/* View Mode Filter */}
        <div className="library-view-modes">
          {['all', 'favorites', 'recent'].map(mode => (
            <button
              key={mode}
              onClick={() => {
                setViewMode(mode);
                setSelectedFolder(null);
              }}
              className={`library-view-mode-btn ${viewMode === mode ? 'active' : ''}`}
            >
              <span className="library-view-mode-icon">
                {mode === 'all' && <BookOpen size={18} />}
                {mode === 'favorites' && <Star size={18} />}
                {mode === 'recent' && <Clock size={18} />}
              </span>
              {mode === 'all' && 'All Bookmarks'}
              {mode === 'favorites' && 'Favorites'}
              {mode === 'recent' && 'Recent'}
            </button>
          ))}
        </div>

        <div className="library-divider" />

        {/* Folder List */}
        <div className="library-folder-list">
          {folders.map(folder => (
            <div
              key={folder.id}
              className={`library-folder-item ${selectedFolder?.id === folder.id ? 'active' : ''}`}
              onClick={() => handleFolderClick(folder)}
            >
              <div className="library-folder-main">
                <span className="library-folder-icon">
                  <Folder size={18} />
                </span>
                <span className="library-folder-name">
                  {folder.name}
                </span>
                <span className="library-folder-count">
                  {folder.bookmark_count}
                </span>
              </div>
              <div className="library-folder-actions">
                <button
                  onClick={(e) => handleToggleFolderShare(folder, e)}
                  className={`library-folder-action-btn ${folder.is_public ? 'shared' : ''}`}
                  title={folder.is_public ? 'Make private' : 'Make public & copy link'}
                >
                  <Share2 size={14} />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    openFolderModal(folder);
                  }}
                  className="library-folder-action-btn"
                  title="Edit folder"
                >
                  <Edit2 size={14} />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDeleteFolder(folder.id);
                  }}
                  className="library-folder-action-btn delete"
                  title="Delete folder"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* CENTER: Bookmarks List */}
      <div className="library-bookmarks-main">
        <div className="library-bookmarks-header">
          <h2 className="library-bookmarks-title">
            {selectedFolder ? `${selectedFolder.name}` : viewMode === 'all' ? 'All Bookmarks' : viewMode === 'favorites' ? 'Favorites' : 'Recent'}
          </h2>
          <span className="library-bookmarks-count">
            {bookmarks.length} bookmark{bookmarks.length !== 1 ? 's' : ''}
          </span>
        </div>

        {bookmarks.length === 0 ? (
          <div className="library-empty-state">
            <div className="library-empty-icon">
              <FileText size={48} />
            </div>
            <div className="library-empty-title">No bookmarks yet</div>
            <div className="library-empty-hint">
              Use the ☆ button on any page to create your first bookmark
            </div>
          </div>
        ) : (
          <div className="library-bookmarks-grid">
            {bookmarks.map(bookmark => (
              <div
                key={bookmark.id}
                onClick={() => handleBookmarkClick(bookmark)}
                className={`library-bookmark-card ${selectedBookmark?.id === bookmark.id ? 'selected' : ''}`}
              >
                <div className="library-bookmark-card-content">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleToggleFavorite(bookmark);
                    }}
                    className={`library-bookmark-favorite-btn ${bookmark.is_favorite ? 'favorited' : ''}`}
                  >
                    <Star size={20} fill={bookmark.is_favorite ? 'currentColor' : 'none'} />
                  </button>

                  <button
                    onClick={(e) => handleToggleBookmarkShare(bookmark, e)}
                    className={`library-bookmark-share-btn ${bookmark.is_public ? 'shared' : ''}`}
                    title={bookmark.is_public ? 'Make private' : 'Make public & copy link'}
                  >
                    <Share2 size={18} />
                  </button>

                  <div className="library-bookmark-info">
                    <div className="library-bookmark-title">
                      {bookmark.title}
                    </div>

                    <div className="library-bookmark-url">
                      {bookmark.url}
                    </div>

                    {bookmark.notes && (
                      <div className="library-bookmark-notes">
                        {bookmark.notes}
                      </div>
                    )}

                    <div className="library-bookmark-meta">
                      {bookmark.folder_name && (
                        <span className="library-bookmark-meta-item">
                          <Folder size={12} /> {bookmark.folder_name}
                        </span>
                      )}
                      {bookmark.visit_count > 0 && (
                        <span className="library-bookmark-meta-item">
                          <Eye size={12} /> {bookmark.visit_count}
                        </span>
                      )}
                      {bookmark.last_visited && (
                        <span className="library-bookmark-meta-item">
                          Last: {new Date(bookmark.last_visited).toLocaleDateString()}
                        </span>
                      )}
                    </div>
                  </div>

                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleNavigateToBookmark(bookmark);
                    }}
                    className="library-bookmark-open-btn"
                  >
                    Open <ArrowRight size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* RIGHT: Bookmark Details Editor */}
      {selectedBookmark && (
        <BookmarkEditor
          bookmark={selectedBookmark}
          folders={folders}
          onSave={async (updates) => {
            await updateBookmark(selectedBookmark.id, updates);
            loadBookmarks();
            setSelectedBookmark({ ...selectedBookmark, ...updates });
          }}
          onDelete={() => handleDeleteBookmark(selectedBookmark.id)}
          onClose={() => setSelectedBookmark(null)}
        />
      )}

      {/* Folder Modal */}
      {showFolderModal && (
        <div className="library-modal-overlay" onClick={() => setShowFolderModal(false)}>
          <div className="library-modal" onClick={(e) => e.stopPropagation()}>
            <h3 className="library-modal-title">
              {editingFolder ? 'Edit Folder' : 'New Folder'}
            </h3>

            <div className="library-form-group">
              <label className="library-form-label">
                Name *
              </label>
              <input
                type="text"
                value={folderFormData.name}
                onChange={(e) => setFolderFormData({ ...folderFormData, name: e.target.value })}
                className="library-form-input"
                placeholder="Work Research"
              />
            </div>

            <div className="library-form-group">
              <label className="library-form-label">
                Description
              </label>
              <textarea
                value={folderFormData.description}
                onChange={(e) => setFolderFormData({ ...folderFormData, description: e.target.value })}
                className="library-form-textarea"
                placeholder="Optional description..."
              />
            </div>

            <div className="library-form-actions">
              <button
                onClick={() => setShowFolderModal(false)}
                className="library-form-btn secondary"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveFolder}
                disabled={!folderFormData.name.trim()}
                className="library-form-btn"
                style={{
                  opacity: folderFormData.name.trim() ? 1 : 0.5,
                  cursor: folderFormData.name.trim() ? 'pointer' : 'not-allowed'
                }}
              >
                {editingFolder ? 'Save' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Bookmark Editor Panel - Shows on the right when a bookmark is selected
 */
function BookmarkEditor({ bookmark, folders, onSave, onDelete, onClose }) {
  const [isEditing, setIsEditing] = useState(false);
  const [formData, setFormData] = useState({
    title: bookmark.title,
    notes: bookmark.notes,
    folder_id: bookmark.folder_id,
    is_favorite: bookmark.is_favorite
  });

  async function handleSave() {
    await onSave(formData);
    setIsEditing(false);
  }

  return (
    <div className="library-editor-panel">
      <div className="library-editor-header">
        <h3 className="library-editor-title">Details</h3>
        <button
          onClick={onClose}
          className="library-editor-close-btn"
        >
          <X size={20} />
        </button>
      </div>

      {isEditing ? (
        <>
          <div className="library-form-group">
            <label className="library-form-label">
              Title
            </label>
            <input
              type="text"
              value={formData.title}
              onChange={(e) => setFormData({ ...formData, title: e.target.value })}
              className="library-form-input"
            />
          </div>

          <div className="library-form-group">
            <label className="library-form-label">
              Folder
            </label>
            <select
              value={formData.folder_id || ''}
              onChange={(e) => setFormData({ ...formData, folder_id: e.target.value || null })}
              className="library-form-select"
            >
              <option value="">No folder</option>
              {folders.map(f => (
                <option key={f.id} value={f.id}>{f.name}</option>
              ))}
            </select>
          </div>

          <div className="library-form-group">
            <label className="library-form-label">
              Notes
            </label>
            <textarea
              value={formData.notes}
              onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
              className="library-form-textarea"
              placeholder="Add your research notes here..."
            />
          </div>

          <div className="library-form-actions">
            <button
              onClick={() => setIsEditing(false)}
              className="library-form-btn secondary"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              className="library-form-btn"
            >
              Save
            </button>
          </div>
        </>
      ) : (
        <div className="library-editor-view">
          <div className="library-editor-section">
            <h4 className="library-editor-bookmark-title">
              {bookmark.title}
            </h4>
            <div className="library-editor-bookmark-url">
              {bookmark.url}
            </div>
          </div>

          {bookmark.folder_name && (
            <div className="library-editor-section">
              <span style={{ fontWeight: '500' }}>Folder:</span> {bookmark.folder_name}
            </div>
          )}

          <div className="library-editor-section">
            <div className="library-editor-section-title">
              Notes
            </div>
            <div className="library-editor-notes-display">
              {bookmark.notes || <span className="library-editor-notes-empty">No notes yet</span>}
            </div>
          </div>

          <div className="library-editor-stats">
            <div>Views: {bookmark.visit_count}</div>
            <div>Created: {new Date(bookmark.created_at).toLocaleString()}</div>
            {bookmark.last_visited && (
              <div>Last visited: {new Date(bookmark.last_visited).toLocaleString()}</div>
            )}
          </div>

          <div className="library-form-actions">
            <button
              onClick={() => setIsEditing(true)}
              className="library-form-btn"
            >
              <Edit2 size={16} /> Edit
            </button>
            <button
              onClick={onDelete}
              className="library-form-btn danger"
            >
              <Trash2 size={16} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
