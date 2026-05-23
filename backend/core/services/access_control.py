class AccessControlService:
    @staticmethod
    def is_premium_organization(org_id):
        """Check if organization requires premium access"""
        # Could be stored in database or as a setting
        premium_orgs = ["MIN_FINANCE", "MIN_DEFENSE"]
        return org_id in premium_orgs

    @staticmethod
    def is_premium_feature(feature_name):
        """Check if a feature requires premium access"""
        premium_features = ["bulk_processing", "advanced_analytics"]
        return feature_name in premium_features

    @staticmethod
    def can_access_organization(user, org_id):
        """Check if user can access this organization's data"""
        if user.is_staff:
            return True

        is_premium = AccessControlService.is_premium_organization(org_id)
        if not is_premium:
            return True  # Everyone can access non-premium orgs

        # Premium orgs require subscription
        return (
            user.is_authenticated
            and user.subscription
            and user.subscription.can_access_premium_data
        )
