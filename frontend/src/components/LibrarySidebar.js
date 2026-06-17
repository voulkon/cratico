import React, { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import {
  getBookmarks,
  getFolders,
  updateBookmark,
  deleteBookmark,
  toggleBookmarkPublic,
  toggleFolderPublic,
} from '../api/bookmarks';
import { useTranslation } from '../contexts/TranslationContext';
import { useAuth } from '../contexts/AuthContext';
import useLibrarySidebarResize from '../hooks/useLibrarySidebarResize';
import useFolderModal from '../hooks/useFolderModal';
import './LibrarySidebar.css';
import {
  LibraryIconInSidebar,
  LibraryFavoriteInSidebar,
  LibraryTimerInSidebar,
  NotebookPenIcon,
  TrashIcon,
  PencilIcon,
  XIcon,
  EyeIcon,
  FolderOpenIcon,
  ChevronRight,
  ChevronDown,
  GripVertical,
  FolderPlusIcon,
  GlobeIcon,
  GlobeLockIcon,
  CopyIcon,
  Share2Icon,
} from './Icons.js';

/**
 * Library Sidebar - Tree-style bookmark manager (like browser bookmarks)
 * Folders expand/collapse in place. Bookmarks can be dragged into folders.
 */
export default function LibrarySidebar({ isOpen, onClose, onBookmarkCountChange }) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { isSignedIn, isLoaded } = useAuth();

  // Custom hooks
  const { sidebarRef, resizeHandleRef, isResizing, handleResizeStart } = useLibrarySidebarResize();
  const {
    showFolderModal,
    editingFolder,
    folderFormData,
    openFolderModal,
    closeFolderModal,
    updateFormField,
    saveFolder,
    handleDeleteFolder: deleteFolderAndRefresh,
  } = useFolderModal({ onFolderChange: loadData });

  // State
  const [folders, setFolders] = useState([]);
  const [bookmarks, setBookmarks] = useState([]);
  const [expandedFolders, setExpandedFolders] = useState(new Set());
  const [viewMode, setViewMode] = useState('all'); // 'all', 'favorites', 'recent'
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedBookmark, setExpandedBookmark] = useState(null);
  const [dragOverFolderId, setDragOverFolderId] = useState(null); // which folder is being hovered during drag
  const [draggingBookmarkId, setDraggingBookmarkId] = useState(null);
  const [editingTitleId, setEditingTitleId] = useState(null); // which bookmark's title is being edited inline
  const [titleDraft, setTitleDraft] = useState(''); // draft value for inline title edit
  const [shareFeedback, setShareFeedback] = useState(null); // { id, type: 'bookmark'|'folder', slug }
  const shareTimeoutRef = useRef(null);
  const notesDraftRef = useRef({});
  const titleInputRef = useRef(null); // ref to the inline title input
  const loadDataRef = useRef(loadData);
  loadDataRef.current = loadData; // keep ref in sync for callbacks

  useEffect(() => {
    if (isOpen && isLoaded && isSignedIn) {
      loadData();
    }
    // eslint-disable-next-line
  }, [isOpen, isSignedIn, isLoaded]);

  // Auto-expand all folders on first load
  useEffect(() => {
    if (folders.length > 0 && expandedFolders.size === 0) {
      setExpandedFolders(new Set(folders.map(f => f.id)));
    }
    // eslint-disable-next-line
  }, [folders]);

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

  // ── Filtering & grouping ──────────────────────────────────────────

  const filteredBookmarks = bookmarks.filter(b => {
    if (viewMode === 'favorites' && !b.is_favorite) return false;
    if (searchQuery === '') return true;
    const q = searchQuery.toLowerCase();
    return (
      b.title.toLowerCase().includes(q) ||
      b.notes?.toLowerCase().includes(q)
    );
  });

  if (viewMode === 'recent') {
    filteredBookmarks.sort(
      (a, b) => new Date(b.last_visited || b.updated_at) - new Date(a.last_visited || a.updated_at)
    );
  }

  // Group into: root bookmarks + bookmarks per folder
  const treeData = React.useMemo(() => {
    const rootBookmarks = [];
    const folderMap = new Map();
    folders.forEach(f => folderMap.set(f.id, { folder: f, bookmarks: [] }));

    filteredBookmarks.forEach(b => {
      if (b.folder_id && folderMap.has(b.folder_id)) {
        folderMap.get(b.folder_id).bookmarks.push(b);
      } else {
        rootBookmarks.push(b);
      }
    });

    return { rootBookmarks, folderMap };
  }, [filteredBookmarks, folders]);

  // ── Drag & Drop ───────────────────────────────────────────────────

  const handleDragStart = useCallback((bookmark, e) => {
    e.dataTransfer.setData('text/plain', bookmark.id.toString());
    e.dataTransfer.effectAllowed = 'move';
    setDraggingBookmarkId(bookmark.id);
  }, []);

  const handleDragEnd = useCallback(() => {
    setDraggingBookmarkId(null);
    setDragOverFolderId(null);
  }, []);

  const handleDragOverFolder = useCallback((folderId, e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDragOverFolderId(folderId);
  }, []);

  const handleDragLeaveFolder = useCallback((folderId) => {
    setDragOverFolderId(prev => prev === folderId ? null : prev);
  }, []);

  const handleDropOnFolder = useCallback((folderId, e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOverFolderId(null);
    setDraggingBookmarkId(null);

    const bookmarkId = parseInt(e.dataTransfer.getData('text/plain'), 10);
    if (!bookmarkId) return;

    const targetFolderId = folderId === '__root__' ? null : folderId;

    updateBookmark(bookmarkId, { folder_id: targetFolderId })
      .then(() => {
        // Auto-expand the target folder so the user sees the result
        if (targetFolderId) {
          setExpandedFolders(prev => new Set([...prev, targetFolderId]));
        }
        loadDataRef.current();
      })
      .catch(console.error);
  }, []);

  // ── Folder toggle ─────────────────────────────────────────────────

  const toggleFolder = useCallback((folderId) => {
    setExpandedFolders(prev => {
      const next = new Set(prev);
      if (next.has(folderId)) next.delete(folderId);
      else next.add(folderId);
      return next;
    });
  }, []);

  // ── Bookmark actions ──────────────────────────────────────────────

  function handleBookmarkClick(bookmark) {
    navigate(bookmark.url);
    onClose();
  }

  function handleToggleNotes(bookmark, e) {
    e.stopPropagation();
    if (expandedBookmark && expandedBookmark !== bookmark.id && notesDraftRef.current[expandedBookmark] !== undefined) {
      const draft = notesDraftRef.current[expandedBookmark];
      delete notesDraftRef.current[expandedBookmark];
      updateBookmark(expandedBookmark, { notes: draft }).then(() => loadData()).catch(console.error);
    }
    const newExpanded = expandedBookmark === bookmark.id ? null : bookmark.id;
    if (newExpanded) {
      notesDraftRef.current[newExpanded] = bookmark.notes || '';
    } else if (notesDraftRef.current[bookmark.id] !== undefined) {
      const draft = notesDraftRef.current[bookmark.id];
      delete notesDraftRef.current[bookmark.id];
      if (draft !== (bookmark.notes || '')) {
        updateBookmark(bookmark.id, { notes: draft }).then(() => loadData()).catch(console.error);
      }
    }
    setExpandedBookmark(newExpanded);
  }

  function handleNotesBlur(bookmark) {
    const draft = notesDraftRef.current[bookmark.id];
    if (draft !== undefined && draft !== (bookmark.notes || '')) {
      delete notesDraftRef.current[bookmark.id];
      updateBookmark(bookmark.id, { notes: draft }).then(() => loadData()).catch(console.error);
    }
  }

  async function handleToggleFavorite(bookmark, e) {
    e.stopPropagation();
    try {
      await updateBookmark(bookmark.id, { is_favorite: !bookmark.is_favorite });
      loadData();
    } catch (error) {
      console.error('Failed to toggle favorite:', error);
    }
  }

  // ── Inline title rename ───────────────────────────────────────────

  function startTitleEdit(bookmark, e) {
    e.stopPropagation();
    // flush any pending notes draft first
    if (expandedBookmark && notesDraftRef.current[expandedBookmark] !== undefined) {
      const draft = notesDraftRef.current[expandedBookmark];
      delete notesDraftRef.current[expandedBookmark];
      updateBookmark(expandedBookmark, { notes: draft }).then(() => loadData()).catch(console.error);
      setExpandedBookmark(null);
    }
    setTitleDraft(bookmark.title);
    setEditingTitleId(bookmark.id);
    // focus the input after render
    requestAnimationFrame(() => {
      titleInputRef.current?.focus();
      titleInputRef.current?.select();
    });
  }

  function commitTitleEdit(bookmarkId) {
    const bookmark = bookmarks.find(b => b.id === bookmarkId);
    if (titleDraft.trim() !== '' && titleDraft.trim() !== bookmark?.title) {
      updateBookmark(bookmarkId, { title: titleDraft.trim() })
        .then(() => loadData())
        .catch(console.error);
    }
    setEditingTitleId(null);
    setTitleDraft('');
  }

  function cancelTitleEdit() {
    setEditingTitleId(null);
    setTitleDraft('');
  }

  function handleTitleKeyDown(bookmarkId, e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitTitleEdit(bookmarkId);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelTitleEdit();
    }
  }

  async function handleDeleteBookmark(bookmarkId, e) {
    e.stopPropagation();
    if (!window.confirm(t('library.deleteBookmarkConfirm'))) return;
    try {
      await deleteBookmark(bookmarkId);
      loadData();
    } catch (error) {
      console.error('Failed to delete bookmark:', error);
    }
  }

  async function handleDeleteFolder(folderId, e) {
    e.stopPropagation();
    if (!window.confirm(t('library.deleteFolderConfirm'))) return;
    try {
      await deleteFolderAndRefresh(folderId);
    } catch (error) {
      console.error('Failed to delete folder:', error);
    }
  }

  // ── Share / Make public ───────────────────────────────────────────

  function buildShareUrl(type, slug) {
    return `${window.location.origin}/share/${type}/${slug}`;
  }

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

  async function handleToggleBookmarkPublic(bookmark, e) {
    e.stopPropagation();
    try {
      await toggleBookmarkPublic(bookmark.id, !bookmark.is_public);
      setShareFeedback(null);
      loadData();
    } catch (error) {
      console.error('Failed to toggle bookmark public:', error);
    }
  }

  async function handleCopyBookmarkUrl(bookmark, e) {
    e.stopPropagation();
    try {
      if (bookmark.is_public) {
        const url = buildShareUrl('bookmark', bookmark.public_slug);
        await copyShareUrl(url);
        setShareFeedback({ id: bookmark.id, type: 'bookmark', slug: bookmark.public_slug });
      } else {
        setShareFeedback({ id: bookmark.id, type: 'bookmark', notShared: true });
      }
    } catch (error) {
      console.error('Failed to copy bookmark URL:', error);
    }
  }

  async function handleUnshareBookmark(bookmark, e) {
    e.stopPropagation();
    try {
      await toggleBookmarkPublic(bookmark.id, false);
      setShareFeedback(null);
      loadData();
    } catch (error) {
      console.error('Failed to unshare bookmark:', error);
    }
  }

  async function handleToggleFolderPublic(folder, e) {
    e.stopPropagation();
    try {
      await toggleFolderPublic(folder.id, !folder.is_public);
      setShareFeedback(null);
      loadData();
    } catch (error) {
      console.error('Failed to toggle folder public:', error);
    }
  }

  async function handleCopyFolderUrl(folder, e) {
    e.stopPropagation();
    try {
      if (folder.is_public) {
        const url = buildShareUrl('folder', folder.public_slug);
        await copyShareUrl(url);
        setShareFeedback({ id: folder.id, type: 'folder', slug: folder.public_slug });
      } else {
        setShareFeedback({ id: folder.id, type: 'folder', notShared: true });
      }
    } catch (error) {
      console.error('Failed to copy folder URL:', error);
    }
  }

  async function handleUnshareFolder(folder, e) {
    e.stopPropagation();
    try {
      await toggleFolderPublic(folder.id, false);
      setShareFeedback(null);
      loadData();
    } catch (error) {
      console.error('Failed to unshare folder:', error);
    }
  }

  // Clear share feedback after 3s
  useEffect(() => {
    if (shareFeedback) {
      if (shareTimeoutRef.current) clearTimeout(shareTimeoutRef.current);
      shareTimeoutRef.current = setTimeout(() => setShareFeedback(null), 3000);
    }
    return () => {
      if (shareTimeoutRef.current) clearTimeout(shareTimeoutRef.current);
    };
  }, [shareFeedback]);

  // ── Render a single bookmark row ──────────────────────────────────

  function renderBookmarkRow(bookmark, isInFolder = false) {
    const isExpanded = expandedBookmark === bookmark.id;
    const isDragging = draggingBookmarkId === bookmark.id;

    return (
      <div key={bookmark.id} className="library-bookmark-item-wrapper">
        <div
          className={`library-bookmark-item ${isExpanded ? 'expanded' : ''} ${isDragging ? 'dragging' : ''} ${isInFolder ? 'indented' : ''}`}
          onClick={() => handleBookmarkClick(bookmark)}
          draggable
          onDragStart={(e) => handleDragStart(bookmark, e)}
          onDragEnd={handleDragEnd}
        >
          {/* Drag handle */}
          <span className="bookmark-drag-handle" title={t('library.dragToReorder')}>
            <GripVertical size={14} />
          </span>

          {/* Favorite toggle */}
          <button
            className="bookmark-favorite-btn"
            onClick={(e) => handleToggleFavorite(bookmark, e)}
            title={bookmark.is_favorite ? t('library.unfavorite') : t('library.favorite')}
          >
            <LibraryFavoriteInSidebar
              size={16}
              fill={bookmark.is_favorite ? 'currentColor' : 'none'}
            />
          </button>

          {/* Content */}
          <div className="bookmark-content">
            {editingTitleId === bookmark.id ? (
              <input
                ref={titleInputRef}
                className="bookmark-title-input"
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                onBlur={() => commitTitleEdit(bookmark.id)}
                onKeyDown={(e) => handleTitleKeyDown(bookmark.id, e)}
                onClick={(e) => e.stopPropagation()}
              />
            ) : (
              <div
                className="bookmark-title editable"
                onClick={(e) => startTitleEdit(bookmark, e)}
                title={t('library.clickToRename')}
              >
                {bookmark.title}
              </div>
            )}
            <div className="bookmark-url">{bookmark.url}</div>
            <div className="bookmark-meta">
              {bookmark.folder_name && (
                <span className="bookmark-folder"><FolderOpenIcon size={12} /> {bookmark.folder_name}</span>
              )}
              {bookmark.visit_count > 0 && (
                <span className="bookmark-visits"><EyeIcon size={12} /> {bookmark.visit_count}</span>
              )}
            </div>
          </div>

          {/* Public/Private toggle – always visible globe */}
          <button
            className={`bookmark-globe-toggle-btn ${bookmark.is_public ? 'public' : 'private'}`}
            onClick={(e) => handleToggleBookmarkPublic(bookmark, e)}
            title={bookmark.is_public ? t('library.makePrivate') : t('library.makePublic')}
          >
            {bookmark.is_public ? <GlobeIcon size={16} /> : <GlobeLockIcon size={16} />}
          </button>

          {/* Share – always visible; copies URL when public, informs when private */}
          <button
            className="bookmark-share-btn"
            onClick={(e) => handleCopyBookmarkUrl(bookmark, e)}
            title={t('library.copyLink')}
          >
            <Share2Icon size={14} />
          </button>

          {/* Notes toggle */}
          <button
            className="bookmark-notes-toggle-btn"
            onClick={(e) => handleToggleNotes(bookmark, e)}
            title={t('library.notes')}
          >
            <NotebookPenIcon size={16} />
          </button>

          {/* Delete */}
          <button
            className="bookmark-delete-btn"
            onClick={(e) => handleDeleteBookmark(bookmark.id, e)}
            title={t('library.delete')}
          >
            <XIcon size={16} />
          </button>
        </div>

        {/* Expanded notes editor */}
        {isExpanded && (
          <div className="bookmark-expanded-details">
            <div className="bookmark-notes-section">
              <div className="notes-header">
                <span className="notes-label">
                  <NotebookPenIcon size={14} /> {t('library.notes')}
                </span>
              </div>
              <div className="notes-editor">
                <textarea
                  className="notes-textarea"
                  defaultValue={bookmark.notes || ''}
                  onChange={(e) => {
                    notesDraftRef.current[bookmark.id] = e.target.value;
                  }}
                  onBlur={() => handleNotesBlur(bookmark)}
                  placeholder={t('library.notesPlaceholder')}
                  autoFocus
                />
              </div>
            </div>
          </div>
        )}

        {/* Share feedback */}
        {shareFeedback?.type === 'bookmark' && shareFeedback.id === bookmark.id && (
          <div className={`share-feedback-toast ${shareFeedback.notShared ? 'not-shared' : ''}`}>
            {shareFeedback.notShared ? (
              <span>{t('library.notShared')}</span>
            ) : (
              <>
                <CopyIcon size={12} />
                <span>{t('library.linkCopied')}</span>
                <button
                  className="share-feedback-unshare"
                  onClick={(e) => handleUnshareBookmark(bookmark, e)}
                >
                  {t('library.unshare')}
                </button>
              </>
            )}
          </div>
        )}
      </div>
    );
  }

  // ── Render a folder node ──────────────────────────────────────────

  function renderFolderNode(folder, bookmarksInFolder) {
    const isExpanded = expandedFolders.has(folder.id);
    const isDragOver = dragOverFolderId === folder.id;

    return (
      <div key={folder.id} className="library-folder-tree-node">
        {/* Folder header – expandable + drop target */}
        <div
          className={`library-folder-tree-header ${isDragOver ? 'drag-over' : ''}`}
          onClick={() => toggleFolder(folder.id)}
          onDragOver={(e) => handleDragOverFolder(folder.id, e)}
          onDragLeave={() => handleDragLeaveFolder(folder.id)}
          onDrop={(e) => handleDropOnFolder(folder.id, e)}
        >
          {/* Expand/collapse chevron */}
          <span className="folder-chevron">
            {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </span>

          {/* Icon */}
          <span className="folder-icon">{folder.icon || <FolderOpenIcon size={16} />}</span>

          {/* Name */}
          <span className="folder-name">{folder.name}</span>

          {/* Count badge */}
          <span className="folder-count">{bookmarksInFolder.length}</span>

          {/* Public/Private toggle – always visible globe */}
          <button
            className={`folder-globe-toggle-btn ${folder.is_public ? 'public' : 'private'}`}
            onClick={(e) => handleToggleFolderPublic(folder, e)}
            title={folder.is_public ? t('library.makePrivate') : t('library.makePublic')}
          >
            {folder.is_public ? <GlobeIcon size={14} /> : <GlobeLockIcon size={14} />}
          </button>

          {/* Share – always visible; copies URL when public, informs when private */}
          <button
            className="folder-share-btn"
            onClick={(e) => handleCopyFolderUrl(folder, e)}
            title={t('library.copyLink')}
          >
            <Share2Icon size={12} />
          </button>

          {/* Actions (visible on hover) */}
          <div className="folder-actions" onClick={(e) => e.stopPropagation()}>
            <button
              className="folder-action-btn"
              onClick={(e) => {
                e.stopPropagation();
                openFolderModal(folder);
              }}
              title={t('library.edit')}
            >
              <PencilIcon size={14} />
            </button>
            <button
              className="folder-action-btn"
              onClick={(e) => handleDeleteFolder(folder.id, e)}
              title={t('library.delete')}
            >
              <TrashIcon size={14} />
            </button>
          </div>
        </div>

        {/* Folder's bookmarks – shown when expanded */}
        {isExpanded && (
          <div className="library-folder-children">
            {/* Share feedback */}
            {shareFeedback?.type === 'folder' && shareFeedback.id === folder.id && (
              <div className={`share-feedback-toast folder-feedback ${shareFeedback.notShared ? 'not-shared' : ''}`}>
                {shareFeedback.notShared ? (
                  <span>{t('library.notShared')}</span>
                ) : (
                  <>
                    <CopyIcon size={12} />
                    <span>{t('library.linkCopied')}</span>
                    <button
                      className="share-feedback-unshare"
                      onClick={(e) => handleUnshareFolder(folder, e)}
                    >
                      {t('library.unshare')}
                    </button>
                  </>
                )}
              </div>
            )}
            {bookmarksInFolder.length === 0 ? (
              <div className="library-folder-empty">
                {t('library.dropBookmarksHere')}
              </div>
            ) : (
              bookmarksInFolder.map(b => renderBookmarkRow(b, true))
            )}
          </div>
        )}
      </div>
    );
  }

  // ── Main render ───────────────────────────────────────────────────

  if (!isOpen) return null;

  const { rootBookmarks, folderMap } = treeData;
  const totalVisible = filteredBookmarks.length;

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
              className={`library-tab ${viewMode === mode ? 'active' : ''}`}
              onClick={() => setViewMode(mode)}
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

        {/* Tree: Root bookmarks (drop zone for removing from folders) */}
        <div className="library-tree-scroll">
          {/* Root bookmarks section */}
          <div
            className={`library-root-section ${dragOverFolderId === '__root__' ? 'drag-over-root' : ''}`}
            onDragOver={(e) => handleDragOverFolder('__root__', e)}
            onDragLeave={() => handleDragLeaveFolder('__root__')}
            onDrop={(e) => handleDropOnFolder('__root__', e)}
          >
            <div className="library-section-header">
              <span className="library-section-title">
                {t('library.bookmarks')}
                <span className="bookmark-count"> ({rootBookmarks.length})</span>
              </span>
              <button className="library-btn-sm" onClick={() => openFolderModal()} title={t('library.newFolder')}>
                <FolderPlusIcon size={18} />
              </button>
            </div>

            {rootBookmarks.map(b => renderBookmarkRow(b, false))}
          </div>

          {/* Folder tree nodes */}
          {Array.from(folderMap.values()).map(({ folder, bookmarks: folderBookmarks }) =>
            renderFolderNode(folder, folderBookmarks)
          )}

          {/* Loading / Empty state */}
          {isLoading && (
            <div className="library-loading">{t('common.loading')}</div>
          )}
          {!isLoading && totalVisible === 0 && folders.length === 0 && (
            <div className="library-empty">
              <div className="empty-icon"><LibraryIconInSidebar size={48} /></div>
              <div className="empty-text">
                {searchQuery ? t('library.noMatchesFound') : t('library.noBookmarksYet')}
              </div>
              <div className="empty-hint">
                {t('library.useStarButton')}
              </div>
            </div>
          )}
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

      {/* Folder Modal - rendered via portal */}
      {showFolderModal && createPortal(
        <div className="library-modal-overlay" onClick={closeFolderModal}>
          <div className="library-modal" onClick={(e) => e.stopPropagation()}>
          <h3 className="modal-title">{editingFolder ? t('library.editFolder') : t('library.newFolder')}</h3>

          <div className="modal-field">
            <label className="modal-label">{t('library.nameRequired')}</label>
              <input
                type="text"
                value={folderFormData.name}
                onChange={(e) => updateFormField('name', e.target.value)}
                className="modal-input"
                placeholder="Work Research"
              />
            </div>

            <div className="modal-field">
            <label className="modal-label">{t('library.description')}</label>
            <textarea
              value={folderFormData.description}
              onChange={(e) => updateFormField('description', e.target.value)}
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
                  onChange={(e) => updateFormField('icon', e.target.value)}
                  className="modal-input"
                  placeholder="📁"
                />
              </div>

              <div className="modal-field">
                <label className="modal-label">Color</label>
                <input
                  type="color"
                  value={folderFormData.color}
                  onChange={(e) => updateFormField('color', e.target.value)}
                  className="modal-color"
                />
              </div>
            </div>

            <div className="modal-actions">
              <button className="modal-btn modal-btn-cancel" onClick={closeFolderModal}>
                Cancel
              </button>
              <button
                className="modal-btn modal-btn-primary"
                onClick={saveFolder}
                disabled={!folderFormData.name.trim()}
              >
                {editingFolder ? 'Save' : 'Create'}
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
