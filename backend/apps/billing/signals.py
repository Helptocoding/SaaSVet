"""Billing intentionally has no Appointment -> Invoice signal.

Closing a MedicalRecord creates the authoritative Checkout. An Appointment
transition alone is not a financial event and must never create an Invoice.
"""
