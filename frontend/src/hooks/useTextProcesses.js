import { useState, useEffect, useRef, useCallback } from 'react';
import apiClient from '../api/client';

/**
 * Hook for document text-process operations on a single decision.
 *
 * Manages the lifecycle of text processes: fetching the available process
 * list, polling while a process is running, and triggering new runs.
 * Exposes `setProcessRuns` / `setProcessResolution` so the page can sync
 * state from its own content-fetch (`fetchDocumentContent`).
 *
 * Usage:
 *   const {
 *     viewMode, setViewMode,
 *     processRuns, setProcessRuns,
 *     processResolution, setProcessResolution,
 *     processList,
 *     activeProcesses, toggleProcess,
 *     processRunning, handleRunProcess,
 *   } = useTextProcesses(id, fetchDocumentContent);
 */
export function useTextProcesses(id, fetchDocumentContent) {
  const processPollRef = useRef(null);

  const [viewMode, setViewMode] = useState('rendered'); // 'rendered' | 'annotated'
  const [processRuns, setProcessRuns] = useState([]);
  const [processResolution, setProcessResolution] = useState(null);
  const [processList, setProcessList] = useState([]);   // { slug, name, description, methods }
  const [activeProcesses, setActiveProcesses] = useState(new Set()); // Set of slugs to show
  const [processRunning, setProcessRunning] = useState(false);

  // ── Fetch available text processes ──────────────────────────────
  useEffect(() => {
    apiClient.get('/processes/').then(res => {
      if (res.data?.processes) setProcessList(res.data.processes);
    }).catch(() => {});
  }, []);

  // ── Poll for running text processes ────────────────────────────
  useEffect(() => {
    const hasRunning = processRuns.some(
      r => r.status === 'PENDING' || r.status === 'RUNNING'
    );
    if (hasRunning) {
      if (processPollRef.current) clearInterval(processPollRef.current);
      processPollRef.current = setInterval(fetchDocumentContent, 4000);
    } else {
      if (processPollRef.current) {
        clearInterval(processPollRef.current);
        processPollRef.current = null;
      }
      setProcessRunning(false);
    }
    return () => {
      if (processPollRef.current) clearInterval(processPollRef.current);
    };
  }, [processRuns, fetchDocumentContent]);

  // ── Toggle a process on/off in the active set ──────────────────
  const toggleProcess = useCallback((slug) => {
    setActiveProcesses(prev => {
      const next = new Set(prev);
      if (next.has(slug)) {
        next.delete(slug);
      } else {
        next.add(slug);
      }
      return next;
    });
  }, []);

  // ── Trigger a text process on demand ────────────────────────────
  const handleRunProcess = useCallback(async (slug) => {
    if (!slug || processRunning) return;
    try {
      setProcessRunning(true);
      const res = await apiClient.post(`/decisions/${id}/processes/run/`, {
        process: slug,
        method: 'regex',
      });
      // If the run completed synchronously (regex), update runs immediately
      if (res.data?.status === 'COMPLETED') {
        setProcessRuns(prev => [
          res.data,
          ...prev.filter(r => r.process !== slug || r.id !== res.data.id),
        ]);
        setProcessRunning(false);
        // Switch to annotated view + auto-enable this process
        setViewMode('annotated');
        setActiveProcesses(prev => new Set([...prev, slug]));
      } else {
        // Optimistically add the pending run; polling will update it
        setProcessRuns(prev => [
          res.data,
          ...prev.filter(r => r.process !== slug || r.id !== res.data.id),
        ]);
      }
    } catch (err) {
      console.error('Error running text process:', err);
      setProcessRunning(false);
    }
  }, [id, processRunning]);

  return {
    viewMode,
    setViewMode,
    processRuns,
    setProcessRuns,
    processResolution,
    setProcessResolution,
    processList,
    activeProcesses,
    toggleProcess,
    processRunning,
    handleRunProcess,
  };
}
