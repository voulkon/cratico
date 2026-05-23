import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getBookmarks,
  getFolders,
  createFolder,
  updateFolder,
  deleteFolder,
  updateBookmark,
  deleteBookmark
} from '../api/bookmarks';
import { useTranslation } from '../contexts/TranslationContext';
import { useAuth } from '../contexts/AuthContext';
import './LibrarySidebar.css';
import {LibraryIconInSidebar, LibraryFavoriteInSidebar, LibraryTimerInSidebar} from './Icons.js';

/**
 * Library Sidebar - Collapsible bookmark manager (like ChatGPT sidebar)
 * Shows folders and bookmarks in a compact, accessible sidebar
 */
export default function LibrarySidebar({ isOpen, onClose, onBookmarkCountChange }) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { isSignedIn, isLoaded } = useAuth();
  const sidebarRef = useRef(null);
  const resizeHandleRef = useRef(null);

  // State
  const [folders, setFolders] = useState([]);
  const [bookmarks, setBookmarks] = useState([]);
  const [selectedFolder, setSelectedFolder] = useState(null);
  const [selectedBookmark, setSelectedBookmark] = useState(null);
  const [viewMode, setViewMode] = useState('all'); // 'all', 'favorites', 'recent'
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [editingNotes, setEditingNotes] = useState(null); // {id, notes}
  const [expandedBookmark, setExpandedBookmark] = useState(null); // id of expanded bookmark
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const saved = localStorage.getItem('librarySidebarWidth');
    return saved ? parseInt(saved, 10) : 400;
  });
  const [isResizing, setIsResizing] = useState(false);

  // Modal states
  const [showFolderModal, setShowFolderModal] = useState(false);
  const [editingFolder, setEditingFolder] = useState(null);
  const [folderFormData, setFolderFormData] = useState({
    name: '',
    description: '',
    color: '#3b82f6',
    icon: '📁'
  });

  // Resize handlers
  const handleResizeStart = useCallback((e) => {
    e.preventDefault();
    setIsResizing(true);
  }, []);

  const handleResizeMove = useCallback((e) => {
    if (!isResizing || !sidebarRef.current) return;

    const newWidth = e.clientX;
    const minWidth = 300;
    const maxWidth = 800;

    if (newWidth >= minWidth && newWidth <= maxWidth) {
      setSidebarWidth(newWidth);
      sidebarRef.current.style.width = `${newWidth}px`;
    }
  }, [isResizing]);

  const handleResizeEnd = useCallback(() => {
    if (isResizing) {
      setIsResizing(false);
      localStorage.setItem('librarySidebarWidth', sidebarWidth.toString());
    }
  }, [isResizing, sidebarWidth]);

  // Resize event listeners
  useEffect(() => {
    if (isResizing) {
      document.addEventListener('mousemove', handleResizeMove);
      document.addEventListener('mouseup', handleResizeEnd);
      document.body.style.cursor = 'ew-resize';
      document.body.style.userSelect = 'none';

      return () => {
        document.removeEventListener('mousemove', handleResizeMove);
        document.removeEventListener('mouseup', handleResizeEnd);
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      };
    }
  }, [isResizing, handleResizeMove, handleResizeEnd]);

  // Apply width on mount and when it changes
  useEffect(() => {
    if (sidebarRef.current) {
      sidebarRef.current.style.width = `${sidebarWidth}px`;
    }
  }, [sidebarWidth]);

  useEffect(() => {
    if (isOpen && isLoaded && isSignedIn) {
      loadData();
    }
    // eslint-disable-next-line
  }, [isOpen, isSignedIn, isLoaded]);

  useEffect(() => {
    if (isSignedIn) {
      loadBookmarks();
    }
    // eslint-disable-next-line
  }, [selectedFolder, viewMode, isSignedIn]);

  async function loadData() {
    setIsLoading(true);
    try {
      const [foldersData, bookmarksData] = await Promise.all([
        getFolders(),
        getBookmarks()
      ]);
      setFolders(foldersData);
      setBookmarks(bookmarksData);
      onBookmarkCountChange?.(bookmarksData.length);
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
      onBookmarkCountChange?.(data.length);
    } catch (error) {
      console.error('Failed to load bookmarks:', error);
    }
  }

  function handleFolderClick(folder) {
    setSelectedFolder(folder?.id === selectedFolder?.id ? null : folder);
    setSelectedBookmark(null);
    setViewMode('all');
  }

  function handleBookmarkClick(bookmark) {
    // Toggle expand to show details and notes editor
    setExpandedBookmark(expandedBookmark === bookmark.id ? null : bookmark.id);
  }

  function handleNavigateToBookmark(bookmark) {
    // Navigate to bookmark and close sidebar
    navigate(bookmark.url);
    onClose();
  }

  async function handleToggleFavorite(bookmark, e) {
    e.stopPropagation();
    try {
      await updateBookmark(bookmark.id, { is_favorite: !bookmark.is_favorite });
      loadBookmarks();
    } catch (error) {
      console.error('Failed to toggle favorite:', error);
    }
  }

  async function handleSaveNotes(bookmarkId) {
    try {
      await updateBookmark(bookmarkId, { notes: editingNotes.notes });
      setEditingNotes(null);
      loadBookmarks();
    } catch (error) {
      console.error('Failed to save notes:', error);
    }
  }

  async function handleDeleteBookmark(bookmarkId, e) {
    e.stopPropagation();
    if (!window.confirm(t('library.deleteBookmarkConfirm'))) return;
    try {
      await deleteBookmark(bookmarkId);
      loadBookmarks();
    } catch (error) {
      console.error('Failed to delete bookmark:', error);
    }
  }

  function openFolderModal(folder = null) {
    setEditingFolder(folder);
    setFolderFormData(folder || {
      name: '',
      description: '',
      color: '#3b82f6',
      icon: '📁'
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

  async function handleDeleteFolder(folderId, e) {
    e.stopPropagation();
    if (!window.confirm(t('library.deleteFolderConfirm'))) return;
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

  const filteredBookmarks = bookmarks.filter(b =>
    searchQuery === '' ||
    b.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    b.notes?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (!isOpen) return null;

  return (
    <>
      {/* Sidebar */}
      <div ref={sidebarRef} className={`library-sidebar ${isOpen ? 'open' : ''}`}>
        {/* Resize Handle */}
        <div
          ref={resizeHandleRef}
          className={`library-sidebar-resize-handle ${isResizing ? 'resizing' : ''}`}
          onMouseDown={handleResizeStart}
        />

        {/* Header */}
        <div className="library-header">
          <h2 className="library-title">
            <span className="library-title-icon"><LibraryIconInSidebar /></span>
            {t('library.myLibrary')}
          </h2>
          <button className="library-close" onClick={onClose} title={t('library.close')}>
            ✕
          </button>
        </div>

        {/* View Mode Tabs */}
        <div className="library-tabs">
          {['all', 'favorites', 'recent'].map(mode => (
            <button
              key={mode}
              className={`library-tab ${viewMode === mode && !selectedFolder ? 'active' : ''}`}
              onClick={() => {
                setViewMode(mode);
                setSelectedFolder(null);
              }}
            >
              {mode === 'all' && <><LibraryIconInSidebar /> {t('library.all')}</>}
              {mode === 'favorites' && <><LibraryFavoriteInSidebar /> {t('library.favorites')}</>}
              {mode === 'recent' && <><LibraryTimerInSidebar /> {t('library.recent')}</>}
            </button>
          ))}
        </div>

        {/* Search */}
        <div className="library-search">
          <input
            type="text"
            placeholder={t('library.searchPlaceholder')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="library-search-input"
          />
        </div>

        {/* Folders Section */}
        <div className="library-section">
          <div className="library-section-header">
            <span className="library-section-title">{t('library.folders')}</span>
            <button className="library-btn-sm" onClick={() => openFolderModal()} title={t('library.newFolder')}>
              +
            </button>
          </div>
          <div className="library-folders">
            {folders.map(folder => (
              <div
                key={folder.id}
                className={`library-folder-item ${selectedFolder?.id === folder.id ? 'active' : ''}`}
                onClick={() => handleFolderClick(folder)}
              >
                <span className="folder-icon">{folder.icon || '📁'}</span>
                <span className="folder-name">{folder.name}</span>
                <span className="folder-count">{folder.bookmark_count}</span>
                <div className="folder-actions">
                  <button
                    className="folder-action-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      openFolderModal(folder);
                    }}
                    title={t('library.edit')}
                  >
                    ✏️
                  </button>
                  <button
                    className="folder-action-btn"
                    onClick={(e) => handleDeleteFolder(folder.id, e)}
                    title={t('library.delete')}
                  >
                    🗑️
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Bookmarks List */}
        <div className="library-section library-bookmarks-section">
          <div className="library-section-header">
            <span className="library-section-title">
              {selectedFolder ? selectedFolder.name : viewMode === 'all' ? t('library.allBookmarks') : viewMode === 'favorites' ? t('library.favorites') : t('library.recent')}
              <span className="bookmark-count"> ({filteredBookmarks.length})</span>
            </span>
          </div>

          <div className="library-bookmarks">
            {isLoading ? (
              <div className="library-loading">{t('common.loading')}</div>
            ) : filteredBookmarks.length === 0 ? (
              <div className="library-empty">
                <div className="empty-icon">📑</div>
                <div className="empty-text">
                  {searchQuery ? t('library.noMatchesFound') : t('library.noBookmarksYet')}
                </div>
                <div className="empty-hint">
                  {t('library.useStarButton')}
                </div>
              </div>
            ) : (
              filteredBookmarks.map(bookmark => {
                const isExpanded = expandedBookmark === bookmark.id;
                const isEditingThis = editingNotes?.id === bookmark.id;

                return (
                  <div key={bookmark.id} className="library-bookmark-item-wrapper">
                    <div
                      className={`library-bookmark-item ${isExpanded ? 'expanded' : ''}`}
                      onClick={() => handleBookmarkClick(bookmark)}
                    >
                      <button
                        className="bookmark-favorite-btn"
                        onClick={(e) => handleToggleFavorite(bookmark, e)}
                      >
                        {bookmark.is_favorite ? '⭐' : '☆'}
                      </button>
                      <div className="bookmark-content">
                        <div className="bookmark-title">{bookmark.title}</div>
                        <div className="bookmark-url">{bookmark.url}</div>
                        <div className="bookmark-meta">
                          {bookmark.folder_name && (
                            <span className="bookmark-folder">📁 {bookmark.folder_name}</span>
                          )}
                          {bookmark.visit_count > 0 && (
                            <span className="bookmark-visits">👁️ {bookmark.visit_count}</span>
                          )}
                        </div>
                      </div>
                      <button
                        className="bookmark-delete-btn"
                        onClick={(e) => handleDeleteBookmark(bookmark.id, e)}
                        title="Delete"
                      >
                        ✕
                      </button>
                    </div>

                    {/* Expanded details with notes editor */}
                    {isExpanded && (
                      <div className="bookmark-expanded-details">
                        <div className="bookmark-actions-row">
                          <button
                            className="bookmark-action-btn primary"
                            onClick={() => handleNavigateToBookmark(bookmark)}
                          >
                            🔗 {t('library.openPage')}
                          </button>
                        </div>

                        <div className="bookmark-notes-section">
                          <div className="notes-header">
                            <span className="notes-label">📝 {t('library.notes')}</span>
                            {!isEditingThis && (
                              <button
                                className="notes-edit-btn"
                                onClick={() => setEditingNotes({ id: bookmark.id, notes: bookmark.notes || '' })}
                              >
                                {bookmark.notes ? `✏️ ${t('library.edit')}` : `+ ${t('library.addNote')}`}
                              </button>
                            )}
                          </div>

                          {isEditingThis ? (
                            <div className="notes-editor">
                              <textarea
                                className="notes-textarea"
                                value={editingNotes.notes}
                                onChange={(e) => setEditingNotes({ ...editingNotes, notes: e.target.value })}
                                placeholder={t('library.notesPlaceholder')}
                                autoFocus
                              />
                              <div className="notes-actions">
                                <button
                                  className="notes-btn cancel"
                                  onClick={() => setEditingNotes(null)}
                                >
                                  {t('common.cancel')}
                                </button>
                                <button
                                  className="notes-btn save"
                                  onClick={() => handleSaveNotes(bookmark.id)}
                                >
                                  {t('common.save')}
                                </button>
                              </div>
                            </div>
                          ) : (
                            <div className="notes-display">
                              {bookmark.notes || <span className="notes-empty">{t('library.noNotesYet')}</span>}
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Full Library Link */}
        <div className="library-footer">
          <button
            className="library-full-link"
            onClick={() => {
              navigate('/library');
              onClose();
            }}
          >
            {t('library.openFullLibrary')}
          </button>
        </div>
      </div>

      {/* Folder Modal */}
      {showFolderModal && (
        <div className="library-modal-overlay" onClick={() => setShowFolderModal(false)}>
          <div className="library-modal" onClick={(e) => e.stopPropagation()}>
          <h3 className="modal-title">{editingFolder ? t('library.editFolder') : t('library.newFolder')}</h3>

          <div className="modal-field">
            <label className="modal-label">{t('library.nameRequired')}</label>
              <input
                type="text"
                value={folderFormData.name}
                onChange={(e) => setFolderFormData({ ...folderFormData, name: e.target.value })}
                className="modal-input"
                placeholder="Work Research"
              />
            </div>

            <div className="modal-field">
            <label className="modal-label">{t('library.description')}</label>
            <textarea
              value={folderFormData.description}
              onChange={(e) => setFolderFormData({ ...folderFormData, description: e.target.value })}
              className="modal-textarea"
              placeholder={t('library.descriptionPlaceholder')}
              />
            </div>

            <div className="modal-row">
              <div className="modal-field">
                <label className="modal-label">Icon</label>
                <input
                  type="text"
                  value={folderFormData.icon}
                  onChange={(e) => setFolderFormData({ ...folderFormData, icon: e.target.value })}
                  className="modal-input"
                  placeholder="📁"
                />
              </div>

              <div className="modal-field">
                <label className="modal-label">Color</label>
                <input
                  type="color"
                  value={folderFormData.color}
                  onChange={(e) => setFolderFormData({ ...folderFormData, color: e.target.value })}
                  className="modal-color"
                />
              </div>
            </div>

            <div className="modal-actions">
              <button className="modal-btn modal-btn-cancel" onClick={() => setShowFolderModal(false)}>
                Cancel
              </button>
              <button
                className="modal-btn modal-btn-primary"
                onClick={handleSaveFolder}
                disabled={!folderFormData.name.trim()}
              >
                {editingFolder ? 'Save' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
