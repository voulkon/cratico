import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../contexts/TranslationContext';
import {
    updateSubscription,
    deleteSubscription,
    triggerCheckNow
} from '../api/notifications';
import {
    Building2,
    User,
    Users,
    UserCheck,
    Filter,
    FileText,
    Zap,
    Pause,
    Play,
    Bell,
    Clock,
    Trash2,
    RefreshCw,
    Edit2,
    Check,
    X,
    BarChart3,
    Mail,
    MailX,
    ChevronDown
} from 'lucide-react';
import './SubscriptionCard.css';

/**
 * SubscriptionCard - Individual subscription display card
 * Shows subscription details with actions
 */
export default function SubscriptionCard({ subscription, onRefresh, cardClass = '' }) {
    const navigate = useNavigate();
    const { t } = useTranslation();
    const [isActionLoading, setIsActionLoading] = useState(false);
    const [isEditingAlias, setIsEditingAlias] = useState(false);
    const [aliasValue, setAliasValue] = useState(subscription.alias || '');

    // Check-now dropdown state
    const [showLookbackDropdown, setShowLookbackDropdown] = useState(false);
    const [customLookbackDays, setCustomLookbackDays] = useState('');
    const [showCustomInput, setShowCustomInput] = useState(false);
    const dropdownRef = useRef(null);
    const customInputRef = useRef(null);

    // Close dropdown on outside click
    useEffect(() => {
        if (!showLookbackDropdown) return;
        const handleClickOutside = (e) => {
            if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
                setShowLookbackDropdown(false);
                setShowCustomInput(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [showLookbackDropdown]);

    // Focus custom input when it appears
    useEffect(() => {
        if (showCustomInput && customInputRef.current) {
            customInputRef.current.focus();
        }
    }, [showCustomInput]);

    // Get icon for subscription type
    const getTypeIcon = (type) => {
        const icons = {
            organization: <Building2 size={16} />,
            entity: <Building2 size={16} />,
            relationship: <Users size={16} />,
            person: <User size={16} />,
            signer: <UserCheck size={16} />,
            filter: <Filter size={16} />
        };
        return icons[type] || <FileText size={16} />;
    };

    // Get display label for subscription type
    const getTypeLabel = (type) => {
        const labels = {
            organization: t('notifications.organization'),
            entity: t('notifications.entity'),
            relationship: t('notifications.relationship'),
            person: t('notifications.person'),
            signer: t('notifications.signer'),
            filter: t('notifications.filterOnly')
        };
        return labels[type] || type;
    };

    // Get target display info
    const getTargetDisplay = () => {
        if (subscription.organization_uid && !subscription.relationship_entity_afm) {
            return {
                primary: subscription.organization_label || subscription.organization_uid,
                secondary: `${t('notifications.uid')}: ${subscription.organization_uid}`,
                link: `/entity/organization/${subscription.organization_uid}`
            };
        }

        if (subscription.entity_afm && !subscription.relationship_org_uid) {
            return {
                primary: subscription.entity_name || subscription.entity_afm,
                secondary: `${t('notifications.afm')}: ${subscription.entity_afm}`,
                link: `/entity/afm/${subscription.entity_afm}`
            };
        }

        if (subscription.relationship_org_uid && subscription.relationship_entity_afm) {
            const orgLabel = subscription.relationship_org_label || subscription.relationship_org_uid;
            const entityName = subscription.relationship_entity_name || subscription.relationship_entity_afm;
            return {
                primary: `${orgLabel} ↔ ${entityName}`,
                secondary: `${subscription.relationship_org_uid} × ${subscription.relationship_entity_afm}`,
                link: `/relationship/entity/${subscription.relationship_entity_afm}/org/${subscription.relationship_org_uid}`
            };
        }

        if (subscription.signer_name) {
            return {
                primary: subscription.signer_name,
                secondary: t('notifications.signer'),
                link: null
            };
        }

        if (subscription.person_name) {
            return {
                primary: subscription.person_name,
                secondary: t('notifications.person'),
                link: null
            };
        }

        return {
            primary: t('notifications.filterBasedSubscription'),
            secondary: t('notifications.customFilters'),
            link: null
        };
    };

    // Save alias
    const handleSaveAlias = async () => {
        if (aliasValue === subscription.alias) {
            setIsEditingAlias(false);
            return;
        }

        setIsActionLoading(true);
        try {
            await updateSubscription(subscription.id, {
                alias: aliasValue || null
            });
            await onRefresh();
            setIsEditingAlias(false);
        } catch (error) {
            console.error('Failed to update alias:', error);
            alert(t('notifications.failedToUpdateAlias'));
        } finally {
            setIsActionLoading(false);
        }
    };

    // Cancel alias edit
    const handleCancelAlias = () => {
        setAliasValue(subscription.alias || '');
        setIsEditingAlias(false);
    };

    // Toggle pause/resume
    const handleTogglePause = async () => {
        setIsActionLoading(true);
        try {
            await updateSubscription(subscription.id, {
                is_active: !subscription.is_active
            });
            await onRefresh();
        } catch (error) {
            console.error('Failed to toggle subscription:', error);
            alert(t('notifications.failedToUpdateSubscription'));
        } finally {
            setIsActionLoading(false);
        }
    };

    // Toggle email notifications
    const handleToggleEmail = async () => {
        setIsActionLoading(true);
        try {
            await updateSubscription(subscription.id, {
                also_send_email: !subscription.also_send_email
            });
            await onRefresh();
        } catch (error) {
            console.error('Failed to toggle email:', error);
            alert(t('notifications.failedToUpdateSubscription'));
        } finally {
            setIsActionLoading(false);
        }
    };

    // Delete subscription
    const handleDelete = async () => {
        if (!window.confirm(t('notifications.confirmDelete'))) {
            return;
        }

        setIsActionLoading(true);
        try {
            await deleteSubscription(subscription.id);
            await onRefresh();
        } catch (error) {
            console.error('Failed to delete subscription:', error);
            alert(t('notifications.failedToDeleteSubscription'));
        } finally {
            setIsActionLoading(false);
        }
    };

    // Check now
    const handleCheckNow = async (lookbackDays = 1) => {
        setIsActionLoading(true);
        setShowLookbackDropdown(false);
        setShowCustomInput(false);
        try {
            await triggerCheckNow(subscription.id, lookbackDays);
            alert(t('notifications.checkComplete'));
            await onRefresh();
        } catch (error) {
            console.error('Failed to check subscription:', error);
            alert(t('notifications.failedToCheckSubscription'));
        } finally {
            setIsActionLoading(false);
        }
    };

    const handleDropdownToggle = (e) => {
        e.stopPropagation();
        setShowLookbackDropdown(prev => !prev);
        setShowCustomInput(false);
        setCustomLookbackDays('');
    };

    const handlePresetClick = (days) => {
        handleCheckNow(days);
    };

    const handleCustomClick = (e) => {
        e.stopPropagation();
        setShowCustomInput(true);
        setCustomLookbackDays('');
    };

    const handleCustomSubmit = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const days = parseInt(customLookbackDays, 10);
        if (days && days > 0) {
            handleCheckNow(days);
        }
    };

    // Navigate to target
    const handleNavigateToTarget = () => {
        const target = getTargetDisplay();
        if (target.link) {
            navigate(target.link);
        }
    };

    // Format last checked time
    const formatLastChecked = (timestamp) => {
        if (!timestamp) return t('notifications.neverChecked');

        const date = new Date(timestamp);
        const now = new Date();
        const diffMs = now - date;
        const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
        const diffDays = Math.floor(diffHours / 24);

        if (diffHours < 1) return t('notifications.justNow');
        if (diffHours < 24) return `${diffHours} ${t('notifications.hoursAgo')}`;
        if (diffDays < 7) return `${diffDays} ${t('notifications.daysAgo')}`;

        return date.toLocaleDateString();
    };

    const target = getTargetDisplay();
    const hasFilters = subscription.keywords?.length > 0 ||
        subscription.amount_min != null ||
        subscription.amount_max != null ||
        subscription.decision_types?.length > 0;

    // Determine display title - use alias if available, otherwise use descriptive placeholder
    const displayTitle = subscription.alias || t('notifications.clickToAddName');
    const hasCustomAlias = !!subscription.alias;

    return (
        <div className={`subscription-card ${!subscription.is_active ? 'paused' : ''} ${cardClass}`}>
            {/* Header */}
            <div className="subscription-card-header">
                <div className="subscription-type">
                    {getTypeIcon(subscription.subscription_type)}
                    <span className="subscription-type-label">
                        {getTypeLabel(subscription.subscription_type)}
                    </span>
                </div>
                <div className={`subscription-status ${subscription.is_active ? 'active' : 'paused'}`}>
                    {subscription.is_active ? (
                        <><Zap size={12} /> {t('notifications.active')}</>
                    ) : (
                        <><Pause size={12} /> {t('notifications.paused')}</>
                    )}
                </div>
            </div>

            {/* Alias/Name - Editable */}
            <div className="subscription-alias">
                {isEditingAlias ? (
                    <div className="subscription-alias-edit">
                        <input
                            type="text"
                            value={aliasValue}
                            onChange={(e) => setAliasValue(e.target.value)}
                            placeholder={t('notifications.enterCustomName')}
                            className="subscription-alias-input"
                            autoFocus
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') handleSaveAlias();
                                if (e.key === 'Escape') handleCancelAlias();
                            }}
                        />
                        <div className="subscription-alias-actions">
                            <button
                                className="alias-btn alias-btn-save"
                                onClick={handleSaveAlias}
                                disabled={isActionLoading}
                                title={t('notifications.save')}
                            >
                                <Check size={14} />
                            </button>
                            <button
                                className="alias-btn alias-btn-cancel"
                                onClick={handleCancelAlias}
                                disabled={isActionLoading}
                                title={t('common.cancel')}
                            >
                                <X size={14} />
                            </button>
                        </div>
                    </div>
                ) : (
                    <div
                        className={`subscription-alias-display ${!hasCustomAlias ? 'no-alias' : ''}`}
                        onClick={() => setIsEditingAlias(true)}
                        title={t('notifications.clickToEdit')}
                    >
                        <span className="subscription-alias-text">{displayTitle}</span>
                        <Edit2 size={14} className="subscription-alias-edit-icon" />
                    </div>
                )}
            </div>

            {/* Target - Always show what this subscription is tracking */}
            <div className="subscription-target">
                <div
                    className={`subscription-target-name ${target.link ? 'clickable' : ''}`}
                    onClick={target.link ? handleNavigateToTarget : undefined}
                    title={target.link ? t('notifications.clickToView') : ''}
                >
                    {target.primary}
                </div>
                {target.secondary && (
                    <div className="subscription-target-secondary">
                        {target.secondary}
                    </div>
                )}
            </div>

            {/* Filters Summary */}
            {hasFilters && (
                <div className="subscription-filters">
                    {subscription.keywords?.length > 0 && (
                        <div className="filter-item">
                            <span className="filter-label">{t('notifications.keywords')}:</span>
                            <span className="filter-value">
                                {subscription.keywords.slice(0, 3).join(', ')}
                                {subscription.keywords.length > 3 && ` +${subscription.keywords.length - 3} ${t('notifications.more')}`}
                            </span>
                        </div>
                    )}

                    {(subscription.amount_min != null || subscription.amount_max != null) && (
                        <div className="filter-item">
                            <span className="filter-label">{t('notifications.amount')}:</span>
                            <span className="filter-value">
                                {subscription.amount_min != null && `≥ €${subscription.amount_min}`}
                                {subscription.amount_min != null && subscription.amount_max != null && ' - '}
                                {subscription.amount_max != null && `≤ €${subscription.amount_max}`}
                            </span>
                        </div>
                    )}

                    {subscription.decision_types?.length > 0 && (
                        <div className="filter-item">
                            <span className="filter-label">{t('notifications.types')}:</span>
                            <span className="filter-value">
                                {subscription.decision_types.length} {t('notifications.selected')}
                            </span>
                        </div>
                    )}
                </div>
            )}

            {/* Metadata */}
            <div className="subscription-metadata">
                <div className="metadata-item">
                    <Bell size={14} className="metadata-icon" />
                    <span className="metadata-text">
                        {subscription.notification_count || 0} {subscription.notification_count !== 1 ? t('notifications.notifications') : t('notifications.notification')}
                    </span>
                </div>
                <div className="metadata-item">
                    <Clock size={14} className="metadata-icon" />
                    <span className="metadata-text">
                        {formatLastChecked(subscription.last_checked_at)}
                    </span>
                </div>
                <div
                    className={`metadata-item metadata-email-toggle ${subscription.also_send_email !== false ? 'email-on' : 'email-off'}`}
                    onClick={handleToggleEmail}
                    title={subscription.also_send_email !== false ? t('notifications.emailNotificationsOn') : t('notifications.emailNotificationsOff')}
                >
                    {subscription.also_send_email !== false ? (
                        <Mail size={14} className="metadata-icon" />
                    ) : (
                        <MailX size={14} className="metadata-icon" />
                    )}
                    <span className="metadata-text">
                        {subscription.also_send_email !== false ? t('notifications.emailOn') : t('notifications.emailOff')}
                    </span>
                </div>
            </div>

            {/* Actions */}
            <div className="subscription-actions">
                <button
                    className="subscription-btn subscription-btn-view-history"
                    onClick={() => navigate(`/notifications/subscriptions/${subscription.id}/history`)}
                    title={t('notifications.viewHistory')}
                >
                    <BarChart3 size={14} />
                    <span className="subscription-btn-text">{t('notifications.viewHistory')}</span>
                </button>

                <div className="subscription-btn-split" ref={dropdownRef}>
                    <button
                        className="subscription-btn subscription-btn-primary subscription-btn-split-main"
                        onClick={() => handleCheckNow(1)}
                        disabled={isActionLoading}
                        title={t('notifications.checkNowTitle')}
                    >
                        {isActionLoading ? '...' : (
                            <>
                                <RefreshCw size={14} />
                                <span className="subscription-btn-text">{t('notifications.checkNow')}</span>
                            </>
                        )}
                    </button>
                    <button
                        className="subscription-btn subscription-btn-primary subscription-btn-split-arrow"
                        onClick={handleDropdownToggle}
                        disabled={isActionLoading}
                        title={t('notifications.checkNowTitle')}
                    >
                        <ChevronDown size={12} />
                    </button>
                    {showLookbackDropdown && (
                        <div className="subscription-lookback-dropdown">
                            <button
                                className="subscription-lookback-item"
                                onClick={() => handlePresetClick(1)}
                            >
                                {t('notifications.checkNowYesterday')}
                            </button>
                            <button
                                className="subscription-lookback-item"
                                onClick={() => handlePresetClick(7)}
                            >
                                {t('notifications.checkNowLast7Days')}
                            </button>
                            <button
                                className="subscription-lookback-item"
                                onClick={() => handlePresetClick(30)}
                            >
                                {t('notifications.checkNowLast30Days')}
                            </button>
                            <button
                                className="subscription-lookback-item"
                                onClick={() => handlePresetClick(90)}
                            >
                                {t('notifications.checkNowLast90Days')}
                            </button>
                            {showCustomInput ? (
                                <form className="subscription-lookback-custom" onSubmit={handleCustomSubmit}>
                                    <input
                                        ref={customInputRef}
                                        type="number"
                                        min="1"
                                        max="3650"
                                        placeholder="30"
                                        value={customLookbackDays}
                                        onChange={(e) => setCustomLookbackDays(e.target.value)}
                                        className="subscription-lookback-custom-input"
                                    />
                                    <span className="subscription-lookback-custom-label">
                                        {t('notifications.checkNowCustomDays')}
                                    </span>
                                    <button
                                        type="submit"
                                        className="subscription-lookback-custom-go"
                                        disabled={!customLookbackDays || parseInt(customLookbackDays, 10) < 1}
                                    >
                                        {t('notifications.checkNowCustomGo')}
                                    </button>
                                </form>
                            ) : (
                                <button
                                    className="subscription-lookback-item subscription-lookback-item-custom"
                                    onClick={handleCustomClick}
                                >
                                    {t('notifications.checkNowCustom')}
                                </button>
                            )}
                        </div>
                    )}
                </div>

                <button
                    className="subscription-btn subscription-btn-secondary"
                    onClick={handleTogglePause}
                    disabled={isActionLoading}
                    title={subscription.is_active ? t('notifications.pauseSubscription') : t('notifications.resumeSubscription')}
                >
                    {subscription.is_active ? (
                        <>
                            <Pause size={14} />
                            <span className="subscription-btn-text">{t('notifications.pause')}</span>
                        </>
                    ) : (
                        <>
                            <Play size={14} />
                            <span className="subscription-btn-text">{t('notifications.resume')}</span>
                        </>
                    )}
                </button>

                <button
                    className="subscription-btn subscription-btn-danger"
                    onClick={handleDelete}
                    disabled={isActionLoading}
                    title={t('notifications.deleteSubscription')}
                >
                    <Trash2 size={14} />
                </button>
            </div>
        </div>
    );
}
