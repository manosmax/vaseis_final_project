"""Συναρτήσεις και σταθερές επιχειρησιακής λογικής (καταστάσεις, χρόνοι παράδοσης κτλ)."""

import calendar
import math
from datetime import datetime, timedelta

# Χαρτογράφηση φιλικών καταστάσεων παραγγελίας σε τιμές βάσης δεδομένων.
ORDER_STATUS_TO_DB = {
    "Εκκρεμεί": "ΕΚΚΡΕΜΕΙ",
    "Σε επεξεργασία": "ΣΕ ΕΠΕΞΕΡΓΑΣΙΑ",
    "Απεστάλη": "ΑΠΕΣΤΑΛΗ",
    "Ακυρώθηκε": "ΑΚΥΡΩΘΗΚΕ",
}
ORDER_STATUS_FROM_DB = {db: display for display, db in ORDER_STATUS_TO_DB.items()}
DEFAULT_ORDER_STATUS = ORDER_STATUS_TO_DB["Εκκρεμεί"]
MAX_DELIVERY_DAYS = 7

# Mapping για συχνότητα παράδοσης ώστε να μεταφράζουμε τα dropdowns σε database enums και αντίστροφα.
DELIVERY_LABEL_TO_DB = {
    "Εβδομαδιαία": "ΕΒΔΟΜΑΔΙΑΙΑ",
    "Δεκαπενθήμερη": "ΔΕΚΑΠΕΝΘΗΜΕΡΗ",
    "Μηνιαία": "ΜΗΝΙΑΙΑ",
}
DELIVERY_DB_TO_LABEL = {db: label for label, db in DELIVERY_LABEL_TO_DB.items()}

PAYMENT_LABEL_TO_DB = {
    "Μετρητά": "ΜΕΤΡΗΤΑ",
    "Κάρτα": "ΚΑΡΤΑ",
    "Πιστωτική": "ΚΑΡΤΑ",
    "Τραπεζική Μεταφορά": "ΤΡΑΠΕΖΙΚΗ_ΜΕΤΑΦΟΡΑ",
    "Τραπεζική Κατάθεση": "ΤΡΑΠΕΖΙΚΗ_ΜΕΤΑΦΟΡΑ",
}
PAYMENT_DB_TO_LABEL = {
    "ΜΕΤΡΗΤΑ": "Μετρητά",
    "ΚΑΡΤΑ": "Κάρτα",
    "ΤΡΑΠΕΖΙΚΗ_ΜΕΤΑΦΟΡΑ": "Τραπεζική Μεταφορά",
}

CONTRACT_DURATION_CHOICES = [
    ("1 μήνας", 1),
    ("3 μήνες", 3),
    ("6 μήνες", 6),
    ("1 έτος", 12),
]
CONTRACT_DURATION_LOOKUP = {label: months for label, months in CONTRACT_DURATION_CHOICES}
DISCOUNT_BY_MONTHS = {
    1: 0,
    3: 5,
    6: 10,
    12: 15,
}


def discount_percent_for_months(months):
    """Υπολογίζει την έκπτωση που αντιστοιχεί στη διάρκεια συμβολαίου."""
    if not months:
        return 0
    percent = 0
    for term, value in sorted(DISCOUNT_BY_MONTHS.items()):
        if months >= term:
            percent = value
    return percent


def contract_duration_months(start_date, end_date):
    """Επιστρέφει τη διάρκεια ενός συμβολαίου σε μήνες μεταξύ δύο ημερομηνιών."""
    if not start_date or not end_date:
        return 0
    months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
    if end_date.day < start_date.day:
        months -= 1
    return max(0, months)


def add_months(start_date, months):
    """Προσθέτει μήνες σε μια ημερομηνία λαμβάνοντας υπόψη το τέλος του μήνα."""
    month = start_date.month - 1 + months
    year = start_date.year + month // 12
    month = month % 12 + 1
    day = min(start_date.day, calendar.monthrange(year, month)[1])
    return start_date.replace(year=year, month=month, day=day)


def _get_item_fields(item):
    """Ομογενοποιεί διαφορετικούς τύπους αντικειμένων/tuple που περιγράφουν προϊόντα."""
    if isinstance(item, dict):
        product_id = item.get("product_id")
        qty = item.get("temaxia_zitisis")
        if qty is None:
            qty = item.get("quantity") or item.get("qty")
        available = item.get("available")
        return product_id, int(qty or 0), int(available or 0)
    if not item:
        return None, 0, 0
    product_id = item[0]
    qty = item[1] if len(item) > 1 else 0
    return product_id, int(qty or 0), 0


def calculate_delivery_days(order_items, available_map=None):
    """Εκτίμηση ημερών παράδοσης με βάση τη διαθεσιμότητα αποθέματος."""
    total_units = 0
    missing_units = 0
    for item in order_items:
        product_id, qty, available = _get_item_fields(item)
        if available_map is not None:
            available = int(available_map.get(product_id, 0))
        total_units += qty
        missing_units += max(0, qty - available)
    if total_units <= 0:
        return 1
    ratio = missing_units / total_units
    days = 1 + math.ceil(ratio * (MAX_DELIVERY_DAYS - 1))
    return min(MAX_DELIVERY_DAYS, max(1, days))


def calculate_delivery_eta(order_time, order_items, available_map=None, now=None):
    """Υπολογίζει ETA και υπολειπόμενο χρόνο παράδοσης."""
    days = calculate_delivery_days(order_items, available_map)
    eta = order_time + timedelta(days=days)
    now = now or datetime.now()
    remaining = eta - now
    if remaining.total_seconds() < 0:
        remaining = timedelta()
    return days, eta, remaining


def format_delivery_remaining(order_time, order_items, available_map=None, now=None):
    """Επιστρέφει περιγραφή στα ελληνικά για τον χρόνο μέχρι την παράδοση."""
    _, _, remaining = calculate_delivery_eta(order_time, order_items, available_map, now)
    if remaining.total_seconds() <= 0:
        return "Παραδόθηκε"
    if remaining < timedelta(days=1):
        return "Σήμερα"
    days_left = math.ceil(remaining.total_seconds() / 86400)
    if days_left == 1:
        return "Σε 1 ημέρα"
    return f"Σε {days_left} ημέρες"
