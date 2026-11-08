import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import {
  getNotificationGroupPeriods,
  getNotificationGroups,
} from '../api/notifications';
import { ChevronLeft, ChevronRight } from '../components/Icons';
import './NotificationsPage.css';

const NotificationsPage = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [periods, setPeriods] = useState([]);
  const [groups, setGroups] = useState([]);
  const [loadingPeriods, setLoadingPeriods] = useState(true);
  const [loadingGroups, setLoadingGroups] = useState(false);
  const [error, setError] = useState(null);

  const requestedPeriod = searchParams.get('period');

  useDocumentTitle(t('notifications.myNotifications'));

  useEffect(() => {
    let cancelled = false;

    const loadPeriods = async () => {
      try {
        setLoadingPeriods(true);
        setError(null);
        const data = await getNotificationGroupPeriods();
        if (!cancelled) {
          setPeriods(data || []);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message);
        }
      } finally {
        if (!cancelled) {
          setLoadingPeriods(false);
        }
      }
    };

    loadPeriods();
    return () => {
      cancelled = true;
    };
  }, []);

  const period = useMemo(() => {
    if (!periods.length) return null;
    if (requestedPeriod) {
      const match = periods.find(
        (entry) => entry.local_date === requestedPeriod
      );
      if (match) return match;
    }
    return periods[0];
  }, [periods, requestedPeriod]);

  useEffect(() => {
    if (!period) {
      setGroups([]);
      return undefined;
    }

    let cancelled = false;
    const loadGroups = async () => {
      try {
        setLoadingGroups(true);
        setError(null);
        const data = await getNotificationGroups({
          local_date: period.local_date,
        });
        if (!cancelled) {
          setGroups(data || []);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message);
        }
      } finally {
        if (!cancelled) {
          setLoadingGroups(false);
        }
      }
    };

    loadGroups();
    return () => {
      cancelled = true;
    };
  }, [period]);

  const periodIndex = useMemo(
    () =>
      period
        ? periods.findIndex((entry) => entry.local_date === period.local_date)
        : -1,
    [period, periods]
  );

  const olderPeriod =
    periodIndex >= 0 && periodIndex < periods.length - 1
      ? periods[periodIndex + 1]
      : null;
  const newerPeriod = periodIndex > 0 ? periods[periodIndex - 1] : null;

  const goToPeriod = (target) => {
    if (!target) return;
    const next = new URLSearchParams(searchParams);
    next.set('period', target.local_date);
    setSearchParams(next);
  };

  const loading = loadingPeriods || loadingGroups;

  return (
    <div className="notifications-page">
      <header className="notifications-page-header">
        <div>
          <h1>{t('notifications.myNotifications')}</h1>
          {period && (
            <p className="notifications-page-subtitle">
              {t('notifications.notificationPeriod')}: {period.period_label}
            </p>
          )}
        </div>

        <div className="notifications-period-nav">
          <button
            type="button"
            className="period-nav-button"
            onClick={() => goToPeriod(olderPeriod)}
            disabled={!olderPeriod || loading}
          >
            <ChevronLeft size={16} />
            <span>{t('notifications.previousPeriod')}</span>
          </button>
          <button
            type="button"
            className="period-nav-button"
            onClick={() => goToPeriod(newerPeriod)}
            disabled={!newerPeriod || loading}
          >
            <span>{t('notifications.nextPeriod')}</span>
            <ChevronRight size={16} />
          </button>
        </div>
      </header>

      {loading && (
        <div className="notifications-page-state">
          <div className="loading-spinner" />
          <p>{t('notifications.loadingNotifications')}</p>
        </div>
      )}

      {!loading && error && (
        <div className="notifications-page-state">
          <p>{error}</p>
          <button
            type="button"
            className="period-nav-button"
            onClick={() => window.location.reload()}
          >
            {t('notifications.aiSummaryRetry')}
          </button>
        </div>
      )}

      {!loading && !error && groups.length === 0 && (
        <div className="notifications-page-state">
          <p>{t('notifications.noNotificationsInPeriod')}</p>
        </div>
      )}

      {!loading && !error && groups.length > 0 && (
        <div className="notification-groups-grid">
          {groups.map((group) => (
            <button
              type="button"
              key={group.id}
              className={`notification-group-card${
                group.is_read ? '' : ' unread'
              }`}
              onClick={() => navigate(`/group/${group.id}`)}
            >
              <div className="notification-group-card-top">
                <span className="notification-group-name">
                  {group.display_name}
                </span>
                {!group.is_read && <span className="notification-unread-dot" />}
              </div>
              <div className="notification-group-period">
                {group.period_label}
              </div>
              <div className="notification-group-count">
                {t('notifications.groupDecisionCount', {
                  count: group.total_match_count || 0,
                })}
              </div>
              {group.decision_publish_start && group.decision_publish_end && (
                <div className="notification-group-range">
                  {new Date(group.decision_publish_start).toLocaleDateString()}{' '}
                  →{' '}
                  {new Date(group.decision_publish_end).toLocaleDateString()}
                </div>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

export default NotificationsPage;
