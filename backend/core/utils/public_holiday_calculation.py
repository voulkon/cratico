from datetime import date, timedelta


def calculate_easter(year: int) -> date:
    """
    Calculate Orthodox Easter date for a given year using Meeus algorithm.

    Args:
        year: Year to calculate Easter for

    Returns:
        Date of Orthodox Easter Sunday
    """
    # Meeus algorithm for Orthodox Easter
    a = year % 4
    b = year % 7
    c = year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = ((d + e + 114) % 31) + 1

    # Add 13 days to convert from Julian to Gregorian calendar
    easter = date(year, month, day)
    easter = easter + timedelta(days=13)

    return easter


def get_greek_holidays(year: int) -> dict[date, str]:
    """
    Get all Greek public holidays for a given year.

    Args:
        year: Year to get holidays for

    Returns:
        Dictionary mapping date to holiday name
    """
    holidays = {}

    # Fixed holidays (same date every year)
    fixed_holidays = [
        (1, 1, "New Year's Day"),
        (1, 6, "Epiphany"),
        (3, 25, "Independence Day"),
        (5, 1, "Labour Day"),
        (8, 15, "Assumption of Mary"),
        (10, 28, "Ochi Day"),
        (12, 25, "Christmas Day"),
        (12, 26, "Boxing Day"),
        (12, 31, "New Year's Eve"),
    ]

    for month, day, name in fixed_holidays:
        holidays[date(year, month, day)] = name

    # Moving holidays (based on Orthodox Easter)
    easter = calculate_easter(year)

    holidays[easter - timedelta(days=48)] = "Clean Monday"  # 48 days before Easter
    holidays[easter - timedelta(days=2)] = "Good Friday"  # Friday before Easter
    holidays[easter] = "Easter Sunday"
    holidays[easter + timedelta(days=1)] = "Easter Monday"
    holidays[easter + timedelta(days=50)] = "Holy Spirit Day"  # 50 days after Easter

    return holidays


def is_greek_holiday(target_date: date) -> tuple[bool, str]:
    """
    Check if a date is a Greek public holiday.

    Args:
        target_date: Date to check

    Returns:
        Tuple of (is_holiday, holiday_name)
    """
    holidays = get_greek_holidays(target_date.year)
    if target_date in holidays:
        return True, holidays[target_date]
    return False, ""
