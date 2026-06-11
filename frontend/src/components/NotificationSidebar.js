import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import { useAuth } from '../contexts/AuthContext';
import {
    getSubscriptions,
    getNotificationBatches,
    dismissBatch,
    markBatchRead,
    markAllNotificationsRead,
    dismissAllNotifications,
    getBatchDecisions
} from '../api/notifications';
import { NOTIFICATION_CONFIG } from '../config/notifications';
import SubscriptionCard from './SubscriptionCard';
import './NotificationSidebar.css';
import { Bell, ClipboardList, Search, Inbox, X, CheckCheck, Trash2 } from 'lucide-react';

/**
 * Notification Sidebar - Collapsible notification manager (like LibrarySidebar)
 * Shows notifications and subscriptions in tabs
 */
export default function NotificationSidebar({ isOpen, onClose, onUnreadCountChange }) {
    const navigate = useNavigate();
    const { t } = useTranslation();
    const { isSignedIn, isLoaded } = useAuth();
    const sidebarRef = useRef(null);
    const resizeHandleRef = useRef(null);

    // State
    const [activeTab, setActiveTab] = useState('subscriptions'); // 'notifications' or 'subscriptions'
    const [subscriptions, setSubscriptions] = useState([]);
    const [notifications, setNotifications] = useState([]);
    const [isLoading, setIsLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [filters, setFilters] = useState({
        status: 'all', // all, active, paused
        type: 'all', // all, organization, entity, relationship, person, signer, filter_only
        sortBy: 'recent' // recent, alphabetical, type, notifications
    });
    const [sidebarWidth, setSidebarWidth] = useState(() => {
        const saved = localStorage.getItem('notificationSidebarWidth');
        return saved ? parseInt(saved, 10) : 400;
    });
    const [isResizing, setIsResizing] = useState(false);

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
            localStorage.setItem('notificationSidebarWidth', sidebarWidth.toString());
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

    // Determine card layout class based on width
    const getCardClass = () => {
        if (sidebarWidth < 350) return 'icon-only';
        if (sidebarWidth < 450) return 'compact';
        return '';
    };


    // Load data function
    const loadData = useCallback(async () => {
        // Don't load if user is not signed in
        if (!isSignedIn) {
            return;
        }

        setIsLoading(true);
        try {
            const [subsData, notifsData] = await Promise.all([
                getSubscriptions(),
                getNotificationBatches()
            ]);

            setSubscriptions(subsData);
            setNotifications(notifsData);

            // Update unread count
            const unreadCount = notifsData.filter(n => !n.is_read).length;
            onUnreadCountChange?.(unreadCount);
        } catch (error) {
            console.error('Failed to load notification data:', error);
        } finally {
            setIsLoading(false);
        }
    }, [onUnreadCountChange, isSignedIn]);

    // Load data when sidebar opens
    useEffect(() => {
        if (isOpen && isLoaded && isSignedIn) {
            loadData();
        }
        // eslint-disable-next-line
    }, [isOpen, loadData, isSignedIn, isLoaded]);

    // Refetch periodically when open
    useEffect(() => {
        if (!isOpen || !isSignedIn) return;

        const interval = setInterval(() => {
            loadData();
        }, NOTIFICATION_CONFIG.UNREAD_COUNT_POLL_INTERVAL);

        return () => clearInterval(interval);
        // eslint-disable-next-line
    }, [isOpen, loadData, isSignedIn]);

    async function handleRefresh() {
        setIsLoading(true);
        try {
            const [subsData, notifsData] = await Promise.all([
                getSubscriptions(),
                getNotificationBatches()
            ]);

            setSubscriptions(subsData);
            setNotifications(notifsData);

            // Update unread count
            const unreadCount = notifsData.filter(n => !n.is_read).length;
            onUnreadCountChange?.(unreadCount);
        } catch (error) {
            console.error('Failed to load notification data:', error);
        } finally {
            setIsLoading(false);
        }
    }

    // Filter and sort subscriptions
    const filteredSubscriptions = useMemo(() => {
        let result = [...subscriptions];

        // Filter by search query
        if (searchQuery) {
            const query = searchQuery.toLowerCase();
            result = result.filter(sub =>
                sub.user_alias?.toLowerCase().includes(query) ||
                sub.target_name?.toLowerCase().includes(query) ||
                sub.organization_uid?.toLowerCase().includes(query) ||
                sub.entity_afm?.toLowerCase().includes(query) ||
                sub.signer_name?.toLowerCase().includes(query) ||
                sub.person_name?.toLowerCase().includes(query)
            );
        }

        // Filter by status
        if (filters.status !== 'all') {
            result = result.filter(sub =>
                filters.status === 'active' ? sub.is_active : !sub.is_active
            );
        }

        // Filter by type
        if (filters.type !== 'all') {
            result = result.filter(sub => sub.subscription_type === filters.type);
        }

        // Sort
        switch (filters.sortBy) {
            case 'alphabetical':
                result.sort((a, b) =>
                    (a.user_alias || a.target_name || '').localeCompare(b.user_alias || b.target_name || '')
                );
                break;
            case 'type':
                result.sort((a, b) => a.subscription_type.localeCompare(b.subscription_type));
                break;
            case 'notifications':
                result.sort((a, b) => (b.notification_count || 0) - (a.notification_count || 0));
                break;
            case 'recent':
            default:
                result.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
                break;
        }

        return result;
    }, [subscriptions, searchQuery, filters]);

    // Handle subscription actions (will be expanded later)
    const handleSubscriptionRefresh = async () => {
        await handleRefresh();
    };

    // Handle notification dismiss
    const handleDismissNotification = async (notificationId, event) => {
        event.stopPropagation(); // Prevent navigation when clicking X
        try {
            await dismissBatch(notificationId);
            // Update local state
            setNotifications(prev => prev.filter(n => n.id !== notificationId));
            // Update unread count
            const unreadCount = notifications.filter(n => !n.is_read && n.id !== notificationId).length;
            onUnreadCountChange?.(unreadCount);
        } catch (error) {
            console.error('Failed to dismiss notification:', error);
        }
    };

    // Handle notification click (navigate to batch detail page)
    const handleNotificationClick = async (notification) => {
        try {
            // Mark as read if not already
            if (!notification.is_read) {
                await markBatchRead(notification.id);
                // Update local state
                setNotifications(prev => prev.map(n =>
                    n.id === notification.id ? { ...n, is_read: true } : n
                ));
                // Update unread count
                const unreadCount = notifications.filter(n => !n.is_read && n.id !== notification.id).length;
                onUnreadCountChange?.(unreadCount);
            }

            // Navigate to batch detail page
            navigate(`/batch/${notification.id}`);
            onClose?.(); // Close sidebar after navigation
        } catch (error) {
            console.error('Failed to handle notification click:', error);
        }
    };

    // Handle mark all as read
    const handleMarkAllRead = async () => {
        try {
            await markAllNotificationsRead();
            // Update local state
            setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
            onUnreadCountChange?.(0);
        } catch (error) {
            console.error('Failed to mark all as read:', error);
        }
    };

    // Handle dismiss all
    const handleDismissAll = async () => {
        if (!window.confirm('Are you sure you want to dismiss all notifications?')) {
            return;
        }
        try {
            await dismissAllNotifications();
            setNotifications([]);
            onUnreadCountChange?.(0);
        } catch (error) {
            console.error('Failed to dismiss all:', error);
        }
    };

    if (!isOpen) return null;

    return (
        <>
            {/* Sidebar */}
            <div ref={sidebarRef} className={`notification-sidebar ${isOpen ? 'open' : ''}`}>
                {/* Resize Handle */}
                <div
                    ref={resizeHandleRef}
                    className={`notification-sidebar-resize-handle ${isResizing ? 'resizing' : ''}`}
                    onMouseDown={handleResizeStart}
                />

                {/* Header */}
                <div className="notification-header">
                    <h2 className="notification-title">
                        <span className="notification-title-icon"><Bell size={20} /></span>
                        {t('notifications.myNotifications')}
                    </h2>
                    <button className="notification-close" onClick={onClose} title={t('notifications.close')}>
                        ✕
                    </button>
                </div>

                {/* Tabs */}
                <div className="notification-tabs">
                    <button
                        className={`notification-tab ${activeTab === 'notifications' ? 'active' : ''}`}
                        onClick={() => setActiveTab('notifications')}
                    >
                        <Bell size={14} />
                        <span>{t('notifications.notifications')}</span>
                        {notifications.filter(n => !n.is_read).length > 0 && (
                            <span className="tab-badge">{notifications.filter(n => !n.is_read).length}</span>
                        )}
                    </button>
                    <button
                        className={`notification-tab ${activeTab === 'subscriptions' ? 'active' : ''}`}
                        onClick={() => setActiveTab('subscriptions')}
                    >
                        <ClipboardList size={14} />
                        <span>{t('notifications.subscriptions')}</span>
                        <span className="tab-count">{subscriptions.length}</span>
                    </button>
                </div>

                {/* Content */}
                {activeTab === 'subscriptions' && (
                    <div className="notification-content">
                        {/* Filters */}
                        <div className="notification-filters">
                            <div className="notification-search">
                                <input
                                    type="text"
                                    placeholder={t('notifications.searchPlaceholder')}
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                    className="notification-search-input"
                                />
                            </div>

                            <div className="notification-filter-row">
                                <select
                                    value={filters.status}
                                    onChange={(e) => setFilters({ ...filters, status: e.target.value })}
                                    className="notification-filter-select"
                                >
                                    <option value="all">{t('notifications.allStatus')}</option>
                                    <option value="active">{t('notifications.active')}</option>
                                    <option value="paused">{t('notifications.paused')}</option>
                                </select>

                                <select
                                    value={filters.type}
                                    onChange={(e) => setFilters({ ...filters, type: e.target.value })}
                                    className="notification-filter-select"
                                >
                                    <option value="all">{t('notifications.allTypes')}</option>
                                    <option value="organization">{t('notifications.organization')}</option>
                                    <option value="entity">{t('notifications.entity')}</option>
                                    <option value="relationship">{t('notifications.relationship')}</option>
                                    <option value="person">{t('notifications.person')}</option>
                                    <option value="signer">{t('notifications.signer')}</option>
                                    <option value="filter_only">{t('notifications.filterOnly')}</option>
                                </select>

                                <select
                                    value={filters.sortBy}
                                    onChange={(e) => setFilters({ ...filters, sortBy: e.target.value })}
                                    className="notification-filter-select"
                                >
                                    <option value="recent">{t('notifications.mostRecent')}</option>
                                    <option value="alphabetical">{t('notifications.alphabetical')}</option>
                                    <option value="type">{t('notifications.byType')}</option>
                                    <option value="notifications">{t('notifications.byCount')}</option>
                                </select>
                            </div>
                        </div>

                        {/* Subscriptions List */}
                        <div className="notification-list">
                            {isLoading ? (
                                <div className="notification-loading">
                                    <div className="loading-spinner"></div>
                                    <p>{t('notifications.loadingSubscriptions')}</p>
                                </div>
                            ) : filteredSubscriptions.length === 0 ? (
                                <div className="notification-empty">
                                    {searchQuery || filters.status !== 'all' || filters.type !== 'all' ? (
                                        <>
                                            <Search size={48} className="empty-icon" />
                                            <h3>{t('notifications.noMatchingSubscriptions')}</h3>
                                            <p>{t('notifications.tryAdjustingFilters')}</p>
                                            <button
                                                className="notification-btn-secondary"
                                                onClick={() => {
                                                    setSearchQuery('');
                                                    setFilters({ status: 'all', type: 'all', sortBy: 'recent' });
                                                }}
                                            >
                                                {t('notifications.clearFilters')}
                                            </button>
                                        </>
                                    ) : (
                                        <>
                                            <Inbox size={48} className="empty-icon" />
                                            <h3>{t('notifications.noSubscriptionsYet')}</h3>
                                            <p>{t('notifications.subscribeToGetNotified')}</p>
                                            <button
                                                className="notification-btn-primary"
                                                onClick={() => navigate('/organizations')}
                                            >
                                                {t('notifications.browseOrganizations')}
                                            </button>
                                        </>
                                    )}
                                </div>
                            ) : (
                                <div className="subscriptions-grid">
                                    {filteredSubscriptions.map(subscription => (
                                        <SubscriptionCard
                                            key={subscription.id}
                                            subscription={subscription}
                                            onRefresh={handleSubscriptionRefresh}
                                            cardClass={getCardClass()}
                                        />
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {activeTab === 'notifications' && (
                    <div className="notification-content">
                        {/* Bulk actions */}
                        {notifications.length > 0 && (
                            <div className="notification-bulk-actions">
                                <button
                                    className="notification-bulk-btn"
                                    onClick={handleMarkAllRead}
                                    disabled={notifications.filter(n => !n.is_read).length === 0}
                                    title="Mark all as read"
                                >
                                    <CheckCheck size={14} />
                                    <span>Mark all read</span>
                                </button>
                                <button
                                    className="notification-bulk-btn danger"
                                    onClick={handleDismissAll}
                                    title="Dismiss all notifications"
                                >
                                    <Trash2 size={14} />
                                    <span>Clear all</span>
                                </button>
                            </div>
                        )}

                        <div className="notification-list">
                            {isLoading ? (
                                <div className="notification-loading">
                                    <div className="loading-spinner"></div>
                                    <p>{t('notifications.loadingNotifications')}</p>
                                </div>
                            ) : notifications.length === 0 ? (
                                <div className="notification-empty">
                                    <Bell size={48} className="empty-icon" />
                                    <h3>{t('notifications.noNotificationsYet')}</h3>
                                    <p>{t('notifications.youllSeeNotifications')}</p>
                                </div>
                            ) : (
                                <div className="notifications-list">
                                    {notifications.map(notification => (
                                        <div
                                            key={notification.id}
                                            className={`notification-item ${!notification.is_read ? 'unread' : ''}`}
                                            onClick={() => handleNotificationClick(notification)}
                                            style={{ cursor: 'pointer' }}
                                        >
                                            <button
                                                className="notification-dismiss-btn"
                                                onClick={(e) => handleDismissNotification(notification.id, e)}
                                                title="Dismiss"
                                            >
                                                <X size={14} />
                                            </button>

                                            <div className="notification-item-header">
                                                <span className="notification-item-type">
                                                    {notification.display_name || notification.subscription?.subscription_type || 'notification'}
                                                </span>
                                                <span className="notification-item-time">
                                                    {new Date(notification.created_at).toLocaleDateString()}
                                                </span>
                                            </div>

                                            {notification.period_label && (
                                                <div className="notification-item-period">
                                                    {notification.period_label}
                                                </div>
                                            )}

                                            <div className="notification-item-content">
                                                <div className="notification-item-subject">
                                                    {notification.match_count === 1
                                                        ? '1 new decision'
                                                        : `${notification.match_count} new decisions`
                                                    }
                                                </div>
                                                {!notification.display_name && (
                                                    <div className="notification-item-ada">
                                                        {notification.subscription?.alias ||
                                                         notification.subscription?.organization?.label ||
                                                         notification.subscription?.entity?.label ||
                                                         'Subscription match'}
                                                    </div>
                                                )}
                                            </div>

                                            {notification.aggregate_stats && notification.aggregate_stats.total_amount && (
                                                <div className="notification-item-reason">
                                                    Total: €{notification.aggregate_stats.total_amount.toLocaleString()}
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </>
    );
}
