from decimal import Decimal

APPOINTMENT_UPCOMING_MINUTES = 15
APPOINTMENT_DELAYED_MINUTES = 20
CASH_DIFFERENCE_NOTIFICATION_THRESHOLD = Decimal("50.00")
FEED_DEFAULT_LIMIT = 20
FEED_MAX_LIMIT = 50

NOTIFICATION_TYPES = (
    "appointment_upcoming",
    "appointment_delayed",
    "stock_low_entered",
    "stock_out",
    "cash_difference",
)

EVENT_TYPES = frozenset({"stock_low_entered", "stock_out", "cash_difference"})
CONDITION_TYPES = frozenset({"appointment_upcoming", "appointment_delayed"})

TYPE_PRIORITY = {
    "appointment_upcoming": "attention",
    "appointment_delayed": "important",
    "stock_low_entered": "attention",
    "stock_out": "important",
    "cash_difference": "important",
}
