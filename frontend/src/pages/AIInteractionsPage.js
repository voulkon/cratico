import React, { useState, useEffect, useCallback } from 'react';
import TopBarSlot from '../components/TopBarSlot';
import { useTranslation } from '../contexts/TranslationContext';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { getAIInteractions, getAIInteractionsSummary, getAIInteractionDetail } from '../api/aiApi';
import { ChevronRight, ChevronDown, X as XIcon } from 'lucide-react';
import './AIInteractionsPage.css';

const AIInteractionsPage = () => {
  const { t } = useTranslation();
  useDocumentTitle(t('aiInteractions.title'));

  const [interactions, setInteractions] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [count, setCount] = useState(0);
  const pageSize = 50;

  // Detail modal
  const [selectedDetail, setSelectedDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [inputExpanded, setInputExpanded] = useState(false);
  const [outputExpanded, setOutputExpanded] = useState(false);

  // Filters
  const [provider, setProvider] = useState('');
  const [trigger, setTrigger] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const loadInteractions = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, page_size: pageSize };
      if (provider) params.provider = provider;
      if (trigger) params.trigger = trigger;
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      const data = await getAIInteractions(params);
      setInteractions(data.results || []);
      setCount(data.count || 0);
    } catch (err) {
      // Silent fail
    } finally {
      setLoading(false);
    }
  }, [page, provider, trigger, dateFrom, dateTo]);

  const loadSummary = useCallback(async () => {
    try {
      const data = await getAIInteractionsSummary();
      setSummary(data);
    } catch (err) {
      // Silent fail
    }
  }, []);

  useEffect(() => {
    Promise.all([loadInteractions(), loadSummary()]).finally(() =>
      setLoading(false)
    );
  }, [loadInteractions, loadSummary]);

  const handleRowClick = async (interaction) => {
    setDetailLoading(true);
    setSelectedDetail(null);
    setInputExpanded(false);
    setOutputExpanded(false);
    try {
      const detail = await getAIInteractionDetail(interaction.id);
      setSelectedDetail(detail);
    } catch (err) {
      setSelectedDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleCloseModal = () => {
    setSelectedDetail(null);
    setInputExpanded(false);
    setOutputExpanded(false);
  };

  const totalPages = Math.ceil(count / pageSize);

  return (
    <div className="ai-interactions-page">
      {/* ── Title rendered into the fixed top bar via portal ──── */}
      <TopBarSlot>
        <div className="ai-interactions-topbar">
          <span className="ai-interactions-title-topbar">{t('aiInteractions.title')}</span>
        </div>
      </TopBarSlot>

      <div className="ai-interactions-container">

        {/* Summary cards */}
        {summary && (
          <div className="ai-interactions-summary-cards">
            <div className="ai-summary-card">
              <span className="ai-summary-label">{t('aiInteractions.totalSpend')}</span>
              <span className="ai-summary-value">
                ${parseFloat(summary.total_cost_usd || 0).toFixed(4)}
              </span>
            </div>
            <div className="ai-summary-card">
              <span className="ai-summary-label">{t('aiInteractions.totalTokens')}</span>
              <span className="ai-summary-value">
                {(summary.total_input_tokens || 0) +
                  (summary.total_output_tokens || 0)}
              </span>
            </div>
            <div className="ai-summary-card">
              <span className="ai-summary-label">{t('aiInteractions.calls')}</span>
              <span className="ai-summary-value">{summary.call_count || 0}</span>
            </div>
            <div className="ai-summary-card">
              <span className="ai-summary-label">{t('aiInteractions.avgCost')}</span>
              <span className="ai-summary-value">
                $
                {summary.call_count
                  ? (
                      parseFloat(summary.total_cost_usd || 0) /
                      summary.call_count
                    ).toFixed(4)
                  : '0.0000'}
              </span>
            </div>
          </div>
        )}

        {/* Filters */}
        <div className="ai-interactions-filters">
          <input
            type="text"
            placeholder={t('aiInteractions.provider')}
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
          />
          <input
            type="text"
            placeholder={t('aiInteractions.trigger')}
            value={trigger}
            onChange={(e) => setTrigger(e.target.value)}
          />
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
          />
          <button onClick={() => { setPage(1); loadInteractions(); }}>{t('aiInteractions.filter')}</button>
        </div>

        {/* Table */}
        <div className="ai-interactions-table-wrapper">
          {loading ? (
            <div className="ai-interactions-loading">{t('common.loading')}</div>
          ) : interactions.length === 0 ? (
            <div className="ai-interactions-empty">{t('aiInteractions.empty')}</div>
          ) : (
            <table className="ai-interactions-table">
              <thead>
                <tr>
                  <th>{t('aiInteractions.date')}</th>
                  <th>{t('aiInteractions.trigger')}</th>
                  <th>{t('aiInteractions.provider')}</th>
                  <th>{t('aiInteractions.model')}</th>
                  <th>{t('aiInteractions.tokensIn')}</th>
                  <th>{t('aiInteractions.tokensOut')}</th>
                  <th>{t('aiInteractions.cost')}</th>
                  <th>{t('aiInteractions.billed')}</th>
                  <th>{t('aiInteractions.status')}</th>
                </tr>
              </thead>
              <tbody>
                {interactions.map((log) => (
                  <tr
                    key={log.id}
                    className="ai-interaction-row"
                    onClick={() => handleRowClick(log)}
                  >
                    <td>{new Date(log.created_at).toLocaleString()}</td>
                    <td>{log.trigger}</td>
                    <td>{log.provider}</td>
                    <td className="ai-model-cell">{log.model_name}</td>
                    <td>{log.input_tokens}</td>
                    <td>{log.output_tokens}</td>
                    <td>${parseFloat(log.cost_usd).toFixed(6)}</td>
                    <td>{log.billed_to}</td>
                    <td>
                      <span
                        className={`ai-status-badge ${log.status.toLowerCase()}`}
                      >
                        {log.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Detail Modal */}
        {(selectedDetail || detailLoading) && (
          <div className="ai-detail-overlay" onClick={handleCloseModal}>
            <div
              className="ai-detail-modal"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="ai-detail-header">
                <h2>{t('aiInteractions.detailTitle')}</h2>
                <button
                  className="ai-detail-close"
                  onClick={handleCloseModal}
                  aria-label="Close"
                >
                  <XIcon size={20} />
                </button>
              </div>

              {detailLoading ? (
                <div className="ai-detail-loading">{t('common.loading')}</div>
              ) : selectedDetail ? (
                <div className="ai-detail-body">
                  {/* Metadata */}
                  <div className="ai-detail-meta">
                    <div className="ai-detail-meta-row">
                      <span className="ai-detail-label">{t('aiInteractions.date')}:</span>
                      <span>{new Date(selectedDetail.created_at).toLocaleString()}</span>
                    </div>
                    <div className="ai-detail-meta-row">
                      <span className="ai-detail-label">{t('aiInteractions.provider')}:</span>
                      <span>{selectedDetail.provider} / {selectedDetail.model_name}</span>
                    </div>
                    <div className="ai-detail-meta-row">
                      <span className="ai-detail-label">{t('aiInteractions.trigger')}:</span>
                      <span>{selectedDetail.trigger}{selectedDetail.trigger_ref ? ` (${selectedDetail.trigger_ref})` : ''}</span>
                    </div>
                    <div className="ai-detail-meta-row">
                      <span className="ai-detail-label">{t('aiInteractions.tokensIn')}:</span>
                      <span>{selectedDetail.input_tokens}</span>
                    </div>
                    <div className="ai-detail-meta-row">
                      <span className="ai-detail-label">{t('aiInteractions.tokensOut')}:</span>
                      <span>{selectedDetail.output_tokens}</span>
                    </div>
                    <div className="ai-detail-meta-row">
                      <span className="ai-detail-label">{t('aiInteractions.cost')}:</span>
                      <span>${parseFloat(selectedDetail.cost_usd).toFixed(6)}</span>
                    </div>
                    <div className="ai-detail-meta-row">
                      <span className="ai-detail-label">{t('aiInteractions.status')}:</span>
                      <span className={`ai-status-badge ${selectedDetail.status.toLowerCase()}`}>
                        {selectedDetail.status}
                      </span>
                    </div>
                  </div>

                  {/* Prompt (input) — collapsible */}
                  {selectedDetail.input_preview && (
                    <div className="ai-detail-section">
                      <button
                        className="ai-detail-section-toggle"
                        onClick={() => setInputExpanded(!inputExpanded)}
                      >
                        <span className="ai-detail-toggle-arrow">
                          {inputExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                        </span>
                        {t('aiInteractions.inputPrompt')}
                        <span className="ai-detail-toggle-hint">
                          ({selectedDetail.input_preview.length.toLocaleString()} chars)
                        </span>
                      </button>
                      {inputExpanded && (
                        <pre className="ai-detail-content">
                          {selectedDetail.input_preview}
                        </pre>
                      )}
                    </div>
                  )}

                  {/* Response (output) — collapsible */}
                  {selectedDetail.output_text && (
                    <div className="ai-detail-section">
                      <button
                        className="ai-detail-section-toggle"
                        onClick={() => setOutputExpanded(!outputExpanded)}
                      >
                        <span className="ai-detail-toggle-arrow">
                          {outputExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                        </span>
                        {t('aiInteractions.outputResponse')}
                        <span className="ai-detail-toggle-hint">
                          ({selectedDetail.output_text.length.toLocaleString()} chars)
                        </span>
                      </button>
                      {outputExpanded && (
                        <pre className="ai-detail-content">
                          {selectedDetail.output_text}
                        </pre>
                      )}
                    </div>
                  )}

                  {/* Error message if failed */}
                  {selectedDetail.error_message && (
                    <div className="ai-detail-section ai-detail-error">
                      <h3 className="ai-detail-section-title">
                        {t('aiInteractions.errorMessage')}
                      </h3>
                      <pre className="ai-detail-content ai-detail-error-content">
                        {selectedDetail.error_message}
                      </pre>
                    </div>
                  )}

                  {/* No content available */}
                  {!selectedDetail.input_preview && !selectedDetail.output_text && !selectedDetail.error_message && (
                    <div className="ai-detail-empty">
                      {t('aiInteractions.noContent')}
                    </div>
                  )}
                </div>
              ) : (
                <div className="ai-detail-empty">
                  {t('aiInteractions.loadError')}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="ai-interactions-pagination">
            <button
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            >
              {t('aiInteractions.prev')}
            </button>
            <span>
              {t('aiInteractions.pageOf', { page, total: totalPages })}
            </span>
            <button
              disabled={page >= totalPages}
              onClick={() => setPage(page + 1)}
            >
              {t('aiInteractions.next')}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default AIInteractionsPage;
