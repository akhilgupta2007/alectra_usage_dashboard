from datetime import datetime, date, timedelta
from typing import Tuple

def is_good_friday(year: int, month: int, day: int) -> bool:
    """
    Computes Good Friday using the Anonymous Gregorian algorithm (Meeus/Jones/Butcher).
    """
    y = year
    a = y % 19
    b = y // 100
    c = y % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    easter_month = (h + l - 7 * m + 114) // 31
    easter_day = ((h + l - 7 * m + 114) % 31) + 1
    
    easter_date = date(y, easter_month, easter_day)
    good_friday = easter_date - timedelta(days=2)
    return month == good_friday.month and day == good_friday.day

def is_ontario_statutory_holiday(dt: date) -> bool:
    """
    Calculation for all official Ontario Statutory National & Provincial Holidays:
    1. New Year's Day (Jan 1)
    2. Family Day (3rd Monday in Feb)
    3. Good Friday (Friday before Easter Sunday)
    4. Victoria Day (Monday before May 25)
    5. Canada Day (July 1)
    6. Civic Holiday / August Long Weekend (1st Monday in August)
    7. Labour Day (1st Monday in September)
    8. Thanksgiving Day (2nd Monday in October)
    9. Christmas Day (Dec 25)
    10. Boxing Day (Dec 26)
    """
    month = dt.month
    day = dt.day
    weekday = dt.weekday() # 0 = Monday, 6 = Sunday

    # 1. New Year's Day
    if month == 1 and day == 1:
        return True

    # 2. Family Day (3rd Monday in Feb: Monday between 15 and 21)
    if month == 2 and weekday == 0 and 15 <= day <= 21:
        return True

    # 3. Good Friday
    if is_good_friday(dt.year, month, day):
        return True

    # 4. Victoria Day (Monday before May 25: Monday between 18 and 24)
    if month == 5 and weekday == 0 and 18 <= day <= 24:
        return True

    # 5. Canada Day (July 1)
    if month == 7 and day == 1:
        return True

    # 6. Civic Holiday (1st Monday in August: Monday between 1 and 7)
    if month == 8 and weekday == 0 and 1 <= day <= 7:
        return True

    # 7. Labour Day (1st Monday in September: Monday between 1 and 7)
    if month == 9 and weekday == 0 and 1 <= day <= 7:
        return True

    # 8. Thanksgiving Day (2nd Monday in October: Monday between 8 and 14)
    if month == 10 and weekday == 0 and 8 <= day <= 14:
        return True

    # 9. Christmas Day
    if month == 12 and day == 25:
        return True

    # 10. Boxing Day
    if month == 12 and day == 26:
        return True

    return False

def is_holiday_or_weekend(dt: date) -> bool:
    """
    Determines whether a given date is a Weekend (Saturday/Sunday) or an official Ontario Statutory Holiday.
    On weekends and holidays, Ontario electricity rates are 100% OFF-PEAK (TOU = 3) all day long.
    """
    # Saturday = 5, Sunday = 6
    if dt.weekday() in (5, 6):
        return True
    return is_ontario_statutory_holiday(dt)

def classify_ulo_slot(dt: datetime) -> str:
    """
    Classifies a localized datetime into one of the 4 official Ontario Ultra-Low Overnight (ULO) rate slots:
    1. 'overnight': 11:00 PM (23:00) to 7:00 AM every day
    2. 'off_peak': 7:00 AM to 11:00 PM on weekends & statutory holidays
    3. 'on_peak': 4:00 PM (16:00) to 9:00 PM (21:00) on weekdays (hours 16, 17, 18, 19, 20)
    4. 'mid_peak': 7:00 AM to 4:00 PM and 9:00 PM to 11:00 PM on weekdays
    """
    hour = dt.hour
    if hour >= 23 or hour < 7:
        return 'overnight'
    
    if is_holiday_or_weekend(dt.date()):
        return 'off_peak'
    
    if 16 <= hour < 21:
        return 'on_peak'
    else:
        return 'mid_peak'
