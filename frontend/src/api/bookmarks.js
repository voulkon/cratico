import apiClient from './client';

/**
 * Bookmark and folder management API functions
 */

// ============ FOLDERS ============

export async function getFolders() {
  const response = await apiClient.get('/user-data/folders/');
  return response.data;
}

export async function createFolder(folderData) {
  const response = await apiClient.post('/user-data/folders/', folderData);
  return response.data;
}

export async function updateFolder(folderId, folderData) {
  const response = await apiClient.patch(`/user-data/${folderId}/folders/`, folderData);
  return response.data;
}

export async function deleteFolder(folderId) {
  await apiClient.delete(`/user-data/${folderId}/folders/`);
}

// ============ BOOKMARKS ============

export async function getBookmarks(params = {}) {
  const response = await apiClient.get('/user-data/bookmarks/', { params });
  return response.data;
}

export async function createBookmark(bookmarkData) {
  const response = await apiClient.post('/user-data/bookmarks/', bookmarkData);
  return response.data;
}

export async function getBookmark(bookmarkId) {
  const response = await apiClient.get(`/user-data/${bookmarkId}/bookmarks/`);
  return response.data;
}

export async function updateBookmark(bookmarkId, bookmarkData) {
  const response = await apiClient.patch(`/user-data/${bookmarkId}/bookmarks/`, bookmarkData);
  return response.data;
}

export async function deleteBookmark(bookmarkId) {
  await apiClient.delete(`/user-data/${bookmarkId}/bookmarks/`);
}

// ============ HELPER FUNCTIONS ============

export function getCurrentPageBookmarkData() {
  const path = window.location.pathname;
  const search = window.location.search;
  const fullUrl = path + search;

  // Use the page title set by useDocumentTitle, stripping the " — CratiCo" suffix.
  // Fall back to "Bookmarked Page" if no page-specific title has been set yet.
  const currentTitle = document.title.replace(/ — CratiCo$/, '');
  const defaultTitle = currentTitle !== 'CratiCo' ? currentTitle : 'Bookmarked Page';

  // Determine view type
  let viewType = 'page';

  if (path.includes('/decision/')) {
    viewType = 'decision';
  } else if (path.includes('/entity/afm/')) {
    viewType = 'entity';
  } else if (path.includes('/entity/')) {
    viewType = 'entity';
  } else if (path.includes('/search')) {
    viewType = 'search';
  } else if (path.includes('/explore/')) {
    viewType = 'temporal';
  } else if (path === '/' || path === '') {
    viewType = 'home';
  } else if (path.includes('/organizations')) {
    viewType = 'organizations';
  }

  // Add shortened URL info
  const urlSuffix = path.length > 30 ? '...' + path.slice(-25) : path;

  return {
    url: fullUrl,
    view_type: viewType,
    default_title: defaultTitle,
    url_display: urlSuffix
  };
}

export async function toggleBookmarkForCurrentPage() {
  const bookmarks = await getBookmarks();
  const currentUrl = window.location.pathname + window.location.search;

  // Check if current page is already bookmarked
  const existing = bookmarks.find(b => b.url === currentUrl);

  if (existing) {
    // Remove bookmark
    await deleteBookmark(existing.id);
    return { action: 'removed', bookmark: existing };
  } else {
    // Add bookmark
    const pageData = getCurrentPageBookmarkData();
    const newBookmark = await createBookmark({
      title: pageData.default_title,
      url: pageData.url,
      view_type: pageData.view_type,
      notes: '',
      is_favorite: false
    });
    return { action: 'added', bookmark: newBookmark };
  }
}

export async function isCurrentPageBookmarked() {
  const bookmarks = await getBookmarks();
  const currentUrl = window.location.pathname + window.location.search;
  return bookmarks.find(b => b.url === currentUrl);
}
