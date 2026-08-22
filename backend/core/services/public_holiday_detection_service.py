from datetime import date, timedelta
from typing import List, Dict, Optional
from holidayfyi import holidays_on_date


class PublicHolidayDetectionService:
    """
    Service for detecting Greek public holidays with weekend adjustment logic.
    
    For government/civil service context:
    - If a public holiday falls on Saturday, the observed holiday is Friday
    - If a public holiday falls on Sunday, the observed holiday is Monday
    - Weekends are already non-working days, so Saturday is considered a low-volume day
    """
    
    COUNTRY_CODE = "GR"
    
    @staticmethod
    def is_public_holiday(check_date: date) -> bool:
        """
        Check if the given date is an actual public holiday in Greece.
        
        Args:
            check_date: The date to check
            
        Returns:
            True if the date is a public holiday, False otherwise
        """
        holidays = holidays_on_date(check_date, [PublicHolidayDetectionService.COUNTRY_CODE])
        return PublicHolidayDetectionService.COUNTRY_CODE in holidays and len(holidays[PublicHolidayDetectionService.COUNTRY_CODE]) > 0
    
    @staticmethod
    def is_observed_holiday(check_date: date) -> bool:
        """
        Check if the given date is an observed public holiday (with weekend adjustments).
        
        Weekend adjustment rules:
        - If a public holiday falls on Saturday, Friday is the observed holiday
        - If a public holiday falls on Sunday, Monday is the observed holiday
        
        Args:
            check_date: The date to check
            
        Returns:
            True if the date is an observed holiday, False otherwise
        """
        # Check if this date itself is a public holiday that doesn't need adjustment
        if PublicHolidayDetectionService.is_public_holiday(check_date):
            # If it's a weekend holiday, it's not the observed day
            if check_date.weekday() == 5:  # Saturday
                return False
            elif check_date.weekday() == 6:  # Sunday
                return False
            return True
        
        # Check if this is a Friday and the next day (Saturday) is a holiday
        if check_date.weekday() == 4:  # Friday
            next_day = check_date + timedelta(days=1)
            if PublicHolidayDetectionService.is_public_holiday(next_day):
                return True
        
        # Check if this is a Monday and the previous day (Sunday) was a holiday
        if check_date.weekday() == 0:  # Monday
            prev_day = check_date - timedelta(days=1)
            if PublicHolidayDetectionService.is_public_holiday(prev_day):
                return True
        
        return False
    
    @staticmethod
    def get_holidays_for_year(year: int) -> List[Dict[str, any]]:
        """
        Get all public holidays for a given year with their observed dates.
        
        Args:
            year: The year to get holidays for
            
        Returns:
            List of dictionaries containing:
            - name: Holiday name
            - actual_date: The actual holiday date
            - observed_date: The observed holiday date (with weekend adjustments)
            - is_weekend_adjusted: Whether the observed date differs from actual
        """
        import holidays as holidays_lib
        
        try:
            yearly_holidays = holidays_lib.country_holidays(
                PublicHolidayDetectionService.COUNTRY_CODE, years=year
            )
        except NotImplementedError:
            return []
        
        # Build the result with observed dates
        result = []
        for actual_date, name in sorted(yearly_holidays.items()):
            observed_date = actual_date
            is_weekend_adjusted = False
            
            # Apply weekend adjustment
            if actual_date.weekday() == 5:  # Saturday
                observed_date = actual_date - timedelta(days=1)  # Friday
                is_weekend_adjusted = True
            elif actual_date.weekday() == 6:  # Sunday
                observed_date = actual_date + timedelta(days=1)  # Monday
                is_weekend_adjusted = True
            
            result.append({
                'name': name,
                'actual_date': actual_date,
                'observed_date': observed_date,
                'is_weekend_adjusted': is_weekend_adjusted
            })
        
        return result
    
    @staticmethod
    def get_day_type(check_date: date) -> str:
        """
        Categorize a date by its type for workload/decision volume purposes.
        
        This is useful for determining expected decision volumes and
        backfill priority.
        
        Args:
            check_date: The date to check
            
        Returns:
            One of:
            - "workday": Normal Monday-Friday, not an observed holiday
            - "saturday": Saturday (whether or not it's an actual holiday)
            - "sunday": Sunday (whether or not it's an actual holiday)  
            - "observed_holiday": Observed public holiday on a weekday (Mon-Fri)
        """
        weekday = check_date.weekday()
        
        # Check weekends first
        if weekday == 5:  # Saturday
            return "saturday"
        elif weekday == 6:  # Sunday
            return "sunday"
        
        # For weekdays (Mon-Fri), check if it's an observed holiday
        if PublicHolidayDetectionService.is_observed_holiday(check_date):
            return "observed_holiday"
        
        return "workday"
    
    @staticmethod
    def is_low_volume_day(check_date: date) -> bool:
        """
        Check if the given date is expected to be a low-volume day.
        
        Low-volume days include:
        - Weekends (Saturday and Sunday)
        - Observed public holidays
        
        Args:
            check_date: The date to check
            
        Returns:
            True if the date is a low-volume day, False otherwise
        """
        # Weekends are low volume
        if check_date.weekday() >= 5:  # Saturday or Sunday
            return True
        
        # Observed holidays are low volume
        if PublicHolidayDetectionService.is_observed_holiday(check_date):
            return True
        
        return False