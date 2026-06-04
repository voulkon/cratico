import { useState, useCallback } from 'react';
import { createFolder, updateFolder, deleteFolder } from '../api/bookmarks';

export const DEFAULT_FOLDER_COLOR = '#3b82f6';
export const DEFAULT_FOLDER_ICON = '📁';

const INITIAL_FOLDER_FORM = {
  name: '',
  description: '',
  color: DEFAULT_FOLDER_COLOR,
  icon: DEFAULT_FOLDER_ICON,
};

/**
 * Hook for managing the folder create/edit modal state and CRUD operations.
 */
export default function useFolderModal({ onFolderChange } = {}) {
  const [showFolderModal, setShowFolderModal] = useState(false);
  const [editingFolder, setEditingFolder] = useState(null);
  const [folderFormData, setFolderFormData] = useState({ ...INITIAL_FOLDER_FORM });

  const openFolderModal = useCallback((folder = null) => {
    setEditingFolder(folder);
    setFolderFormData(
      folder
        ? {
            name: folder.name || '',
            description: folder.description || '',
            color: folder.color || DEFAULT_FOLDER_COLOR,
            icon: folder.icon || DEFAULT_FOLDER_ICON,
          }
        : { ...INITIAL_FOLDER_FORM }
    );
    setShowFolderModal(true);
  }, []);

  const closeFolderModal = useCallback(() => {
    setShowFolderModal(false);
    setEditingFolder(null);
  }, []);

  const updateFormField = useCallback((field, value) => {
    setFolderFormData((prev) => ({ ...prev, [field]: value }));
  }, []);

  const saveFolder = useCallback(async () => {
    try {
      if (editingFolder) {
        await updateFolder(editingFolder.id, folderFormData);
      } else {
        await createFolder(folderFormData);
      }
      setShowFolderModal(false);
      setEditingFolder(null);
      onFolderChange?.();
    } catch (error) {
      console.error('Failed to save folder:', error);
      throw error;
    }
  }, [editingFolder, folderFormData, onFolderChange]);

  const handleDeleteFolder = useCallback(
    async (folderId) => {
      try {
        await deleteFolder(folderId);
        onFolderChange?.();
        return true;
      } catch (error) {
        console.error('Failed to delete folder:', error);
        throw error;
      }
    },
    [onFolderChange]
  );

  return {
    showFolderModal,
    editingFolder,
    folderFormData,
    openFolderModal,
    closeFolderModal,
    updateFormField,
    saveFolder,
    handleDeleteFolder,
  };
}
