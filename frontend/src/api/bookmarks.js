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

  // Determine view type and generate better title
  let viewType = 'page';
  let defaultTitle = 'Bookmarked Page';

  if (path.includes('/decision/')) {
    viewType = 'decision';
    const decisionId = path.split('/decision/')[1]?.split('/')[0];
    defaultTitle = `Decision ${decisionId || ''}`;
  } else if (path.includes('/entity/afm/')) {
    viewType = 'entity';
    const afm = path.split('/entity/afm/')[1]?.split('/')[0];
    defaultTitle = `AFM Entity ${afm || ''}`;
  } else if (path.includes('/entity/')) {
    viewType = 'entity';
    const parts = path.split('/entity/');
    if (parts[1]) {
      const [entityType, entityId] = parts[1].split('/');
      defaultTitle = `${entityType} ${entityId || ''}`;
    }
  } else if (path.includes('/search')) {
    viewType = 'search';
    const params = new URLSearchParams(search);
    const query = params.get('q') || params.get('query');
    defaultTitle = query ? `Search: ${query}` : 'Search Results';
  } else if (path.includes('/explore/temporal')) {
    viewType = 'temporal';
    const datePart = path.split('/explore/temporal/')[1];
    defaultTitle = datePart ? `Temporal: ${datePart}` : 'Temporal View';
  } else if (path.includes('/explore/month')) {
    viewType = 'temporal';
    const parts = path.split('/explore/month/');
    if (parts[1]) {
      const [year, month] = parts[1].split('/');
      defaultTitle = `Month: ${year}-${month || ''}`;
    }
  } else if (path.includes('/explore/week')) {
    viewType = 'temporal';
    const parts = path.split('/explore/week/');
    if (parts[1]) {
      const [year, week] = parts[1].split('/');
      defaultTitle = `Week: ${year}-${week || ''}`;
    }
  } else if (path === '/' || path === '') {
    viewType = 'home';
    defaultTitle = 'Home Page';
  } else if (path.includes('/organizations')) {
    viewType = 'organizations';
    defaultTitle = 'Organizations';
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
