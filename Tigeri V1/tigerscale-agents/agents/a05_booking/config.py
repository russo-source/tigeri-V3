"""Contain config backend logic."""
# Constant for booking config.
BOOKING_CONFIG = {
    "confidence_threshold": 0.7,
    "valid_actions": [
        "create_booking",
        "cancel_booking",
        "reschedule_booking",
        "check_availability"
    ],
    "default_duration_minutes": 60,
    "reminder_hours": [24, 1],
    "business_hours": {
        "start": "09:00",
        "end": "18:00"
    },
}