"""Business-layer συναρτήσεις: χρήστες, συμβόλαια, αποθήκη και παραγγελίες."""

import hashlib
import random
import secrets
from collections import defaultdict
from datetime import datetime

import mysql.connector

from db import Database, SQL, with_in_clause
from domain import (
    CONTRACT_DURATION_CHOICES,
    CONTRACT_DURATION_LOOKUP,
    DEFAULT_ORDER_STATUS,
    DELIVERY_DB_TO_LABEL,
    DELIVERY_LABEL_TO_DB,
    DISCOUNT_BY_MONTHS,
    ORDER_STATUS_FROM_DB,
    ORDER_STATUS_TO_DB,
    PAYMENT_DB_TO_LABEL,
    PAYMENT_LABEL_TO_DB,
    add_months,
    calculate_delivery_days,
    calculate_delivery_eta,
    contract_duration_months,
    discount_percent_for_months,
    format_delivery_remaining,
)

SHIPMENT_STATUS_LABELS = {
    "ΟΛΟΚΛΗΡΩΜΕΝΗ": "Αποστολή ολοκληρώθηκε",
    "ΜΕΡΙΚΗ": "Αποστολή μερική",
}


def _group_order_items(order_ids):
    """Συγκεντρώνει τα προϊόντα κάθε παραγγελίας σε λεξικό για εύκολη πρόσβαση."""
    if not order_ids:
        return {}
    query = with_in_clause(SQL.ORDER_ITEMS_WITH_STOCK, order_ids)
    params = list(order_ids) + list(order_ids)
    items = Database.fetch_all(query, params)
    grouped = defaultdict(list)
    for item in items:
        grouped[item["order_id"]].append(item)
    return grouped


def _normalize_status_filter(status_label):
    """Μετατρέπει την φιλική περιγραφή κατάστασης σε κωδικό βάσης."""
    if not status_label or status_label == "Όλες":
        return None
    return ORDER_STATUS_TO_DB.get(status_label, status_label)


class InventoryRepository:
    """Συναρτήσεις σχετικές με το απόθεμα και τα διαθέσιμα προϊόντα."""

    @staticmethod
    def fetch_available_counts(product_ids):
        """Επιστρέφει λεξικό με διαθέσιμα τεμάχια για συγκεκριμένα προϊόντα."""
        if not product_ids:
            return {}
        query = with_in_clause(SQL.INVENTORY_AVAILABLE_BY_IDS, product_ids)
        rows = Database.fetch_all(query, product_ids)
        return {row["product_id"]: int(row["available"]) for row in rows}

    @staticmethod
    def fetch_all_stock():
        """Φέρνει συγκεντρωτικό απόθεμα για όλα τα προϊόντα (χρησιμοποιείται σε εκτιμήσεις)."""
        rows = Database.fetch_all(SQL.INVENTORY_ALL_STOCK)
        return {row["product_id"]: int(row["available"]) for row in rows}


class AuthManager:
    """Διαχείριση χρηστών: εγγραφή, σύνδεση και χειρισμός κωδικών."""

    ITERATIONS = 120000

    @classmethod
    def hash_password(cls, raw_password):
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", raw_password.encode("utf-8"), salt, cls.ITERATIONS)
        return f"{salt.hex()}${digest.hex()}"

    @classmethod
    def verify_password(cls, stored_value, raw_password):
        try:
            salt_hex, digest_hex = stored_value.split("$")
        except ValueError:
            return False
        test_digest = hashlib.pbkdf2_hmac(
            "sha256", raw_password.encode("utf-8"), bytes.fromhex(salt_hex), cls.ITERATIONS
        ).hex()
        return secrets.compare_digest(test_digest, digest_hex)

    @classmethod
    def register(cls, username, password, role, full_name, phone, pharmacy_details=None):
        """Δημιουργεί νέο χρήστη και, ανάλογα με τον ρόλο, ενημερώνει τα αντίστοιχα tables."""
        username = (username or "").strip().lower()
        if not username or not password or not role:
            return False, "Παρακαλώ συμπληρώστε όλα τα υποχρεωτικά πεδία."

        # Ελέγχουμε αν υπάρχει ήδη username ώστε να αποφύγουμε διπλές εγγραφές.
        if Database.fetch_one(SQL.USER_EXISTS, (username,)):
            return False, "Το όνομα χρήστη υπάρχει ήδη."

        afm = None
        address = None
        if role == "Φαρμακείο":
            if not pharmacy_details:
                return False, "Συμπληρώστε τα στοιχεία του φαρμακείου."
            afm = pharmacy_details.get("afm")
            address = pharmacy_details.get("address")
            if not afm or not address:
                return False, "Το ΑΦΜ και η διεύθυνση είναι υποχρεωτικά."
            # Το ΑΦΜ πρέπει να είναι μοναδικό ώστε να μην υπάρχουν πολλαπλά φαρμακεία με ίδια ταυτότητα.
            if Database.fetch_one(SQL.PHARMACY_AFM_EXISTS, (afm,)):
                return False, "Το ΑΦΜ χρησιμοποιείται ήδη."
        elif role != "Προσωπικό Αποθήκης":
            return False, "Άγνωστος ρόλος."

        hashed = cls.hash_password(password)
        try:
            with Database.transaction(dictionary=False) as cur:
                # Εισαγωγή στον βασικό πίνακα χρηστών και πρόσθετα στοιχεία ανά ρόλο.
                cur.execute(
                    SQL.INSERT_USER,
                    (username, full_name or username, hashed, phone or ""),
                )
                if role == "Προσωπικό Αποθήκης":
                    # Αν είναι προσωπικό, συνδέουμε το username στον πίνακα PROSOPIKO.
                    cur.execute(SQL.INSERT_STAFF, (username,))
                else:
                    # Αν είναι φαρμακείο, εισάγουμε το ΑΦΜ/διεύθυνση στον πίνακα FARMAKEIO.
                    cur.execute(SQL.INSERT_PHARMACY, (username, afm, address))
            return True, "Επιτυχής εγγραφή!"
        except mysql.connector.Error as exc:
            return False, f"Σφάλμα βάσης: {exc.msg}"

    @classmethod
    def login(cls, username, password):
        """Ελέγχει τα στοιχεία σύνδεσης και επιστρέφει την ιδιότητα του χρήστη."""
        username = (username or "").strip().lower()
        user = Database.fetch_one(SQL.LOGIN_WITH_ROLE, (username,))
        if not user:
            return False, "Το όνομα χρήστη δεν βρέθηκε.", None

        if not cls.verify_password(user["hashed_password"], password):
            return False, "Λανθασμένος κωδικός.", None

        if user.get("pharmacy_username"):
            return True, "Επιτυχία", "Φαρμακείο"
        if user.get("staff_username"):
            return True, "Επιτυχία", "Προσωπικό Αποθήκης"
        return False, "Ο λογαριασμός δεν έχει εκχωρηθεί σε ρόλο.", None


class PharmacyRepository:
    """Λογική που σχετίζεται με τα φαρμακεία, τα προϊόντα και τα συμβόλαια."""

    @staticmethod
    def fetch_products():
        """Επιστρέφει όλα τα προϊόντα με τα συνολικά διαθέσιμα τεμάχια."""
        return Database.fetch_all(SQL.PHARMACY_PRODUCTS)

    @staticmethod
    def get_afm(username):
        """Βρίσκει το ΑΦΜ που αντιστοιχεί στο δοθέν username."""
        row = Database.fetch_one(SQL.PHARMACY_AFM, (username,))
        return row["afm"] if row else None

    @staticmethod
    def _annotate_contract(row):
        """Εμπλουτίζει μια εγγραφή συμβολαίου με παράγωγα πεδία για εμφάνιση."""
        today = datetime.utcnow().date()
        end_date = row["hm_liksis"]
        row["is_active"] = bool(end_date and end_date > today)
        row["is_expired"] = bool(end_date and end_date <= today)
        duration_months = row.get("diarkeia_mhnwn")
        if not duration_months:
            duration_months = contract_duration_months(row.get("hm_ypografis"), row.get("hm_liksis"))
        row["duration_months"] = int(duration_months or 0)
        row["discount_percent"] = discount_percent_for_months(row["duration_months"])
        row["frequency_label"] = DELIVERY_DB_TO_LABEL.get(row["suxnotita_paradosis"], row["suxnotita_paradosis"])
        row["payment_label"] = PAYMENT_DB_TO_LABEL.get(row["tropos_pliromis"], row["tropos_pliromis"])
        return row

    @staticmethod
    def fetch_contracts(username):
        """Επιστρέφει λίστα συμβολαίων που σχετίζονται με το φαρμακείο."""
        if not username:
            return []
        rows = Database.fetch_all(SQL.PHARMACY_CONTRACTS, (username,))
        return [PharmacyRepository._annotate_contract(row) for row in rows]

    @staticmethod
    def get_active_discount(username):
        """Υπολογίζει την έκπτωση από το ενεργό συμβόλαιο (αν υπάρχει)."""
        contract = PharmacyRepository.fetch_contract(username)
        if contract and contract.get("is_active"):
            return int(contract.get("discount_percent") or 0)
        return 0

    @staticmethod
    def select_current_contract(contracts):
        """Επιλέγει το ενεργό συμβόλαιο, αλλιώς το πιο πρόσφατο."""
        if not contracts:
            return None
        for contract in contracts:
            if contract.get("is_active"):
                return contract
        return contracts[0]

    @staticmethod
    def fetch_contract(username):
        """Επιστρέφει το τρέχον συμβόλαιο του φαρμακείου."""
        contracts = PharmacyRepository.fetch_contracts(username)
        return PharmacyRepository.select_current_contract(contracts)

    @staticmethod
    def sign_contract(username, duration_label, delivery_label, payment_label):
        """Δημιουργεί νέο συμβόλαιο εφόσον δεν υπάρχει ενεργό."""
        afm = PharmacyRepository.get_afm(username)
        if not afm:
            return False, "Δεν βρέθηκαν στοιχεία φαρμακείου."
        months = CONTRACT_DURATION_LOOKUP.get(duration_label)
        if months is None:
            try:
                months = int(duration_label)
            except (TypeError, ValueError):
                months = 0
        if months <= 0:
            return False, "Επιλέξτε έγκυρη διάρκεια συμβολαίου."
        delivery_value = DELIVERY_LABEL_TO_DB.get(delivery_label)
        if not delivery_value:
            return False, "Μη έγκυρη συχνότητα παράδοσης."
        payment_value = PAYMENT_LABEL_TO_DB.get(payment_label)
        if not payment_value:
            return False, "Μη έγκυρος τρόπος πληρωμής."
        # Έλεγχος για ενεργό συμβόλαιο ώστε να αποτραπεί διπλή υπογραφή.
        existing = Database.fetch_one(SQL.ACTIVE_CONTRACT, (username, datetime.utcnow().date()))
        if existing:
            return False, "Υπάρχει ήδη ενεργό συμβόλαιο."
        start_date = datetime.utcnow().date()
        end_date = add_months(start_date, months)
        try:
            with Database.transaction(dictionary=False) as cur:
                cur.execute(
                    SQL.INSERT_CONTRACT,
                    (delivery_value, payment_value, afm, start_date, end_date, months),
                )
            return True, "Το συμβόλαιο υπογράφηκε με επιτυχία."
        except mysql.connector.Error as exc:
            return False, f"Σφάλμα βάσης: {exc.msg}"

    @staticmethod
    def cancel_contract(username):
        """Μαρκάρει το συμβόλαιο ως λήξαν την τρέχουσα ημερομηνία."""
        contract = PharmacyRepository.fetch_contract(username)
        if not contract or not contract.get("is_active"):
            return False, "Δεν υπάρχει ενεργό συμβόλαιο προς ακύρωση."
        try:
            with Database.transaction(dictionary=False) as cur:
                cur.execute(SQL.CANCEL_CONTRACT, (datetime.utcnow().date(), contract["agreement_id"]))
            return True, "Το συμβόλαιο ακυρώθηκε."
        except mysql.connector.Error as exc:
            return False, f"Σφάλμα βάσης: {exc.msg}"

    @staticmethod
    def create_order(username, items, total_cost=None):
        """Δημιουργεί παραγγελία φαρμακείου και γραμμές προϊόντων με τυχόν έκπτωση."""
        if not items:
            return False, "Δεν υπάρχουν προϊόντα στην παραγγελία."

        afm = PharmacyRepository.get_afm(username)
        if not afm:
            return False, "Δεν βρέθηκε το συνδεδεμένο φαρμακείο."

        # Αντιστοίχηση προϊόντων με τιμές βάσης για σωστό υπολογισμό κόστους.
        product_ids = [product_id for product_id, _, _ in items]
        query = with_in_clause(SQL.PRODUCT_PRICES_BY_IDS, product_ids)
        # Παίρνουμε όλες τις τιμές (arx_kostos_temaxiou) για να αποφύγουμε πολλαπλά trips στη βάση.
        price_rows = Database.fetch_all(query, product_ids)
        price_map = {row["product_id"]: float(row["arx_kostos_temaxiou"]) for row in price_rows}
        if len(price_map) != len(product_ids):
            return False, "Δεν βρέθηκαν στοιχεία τιμών για όλα τα προϊόντα."

        base_total = 0.0
        for product_id, quantity, _ in items:
            base_total += int(quantity) * price_map.get(product_id, 0.0)
        discount_percent = PharmacyRepository.get_active_discount(username)
        discount_amount = base_total * (discount_percent / 100)
        discounted_total = max(0.0, base_total - discount_amount)

        try:
            with Database.transaction(dictionary=False) as cur:
                # Εισαγωγή κεφαλίδας παραγγελίας και κατόπιν γραμμών προϊόντων.
                cur.execute(
                    SQL.INSERT_ORDER,
                    (DEFAULT_ORDER_STATUS, discounted_total, discount_percent, afm, datetime.now()),
                )
                order_id = cur.lastrowid
                # Δημιουργούμε ένα bulk list για executemany ώστε να είναι αποδοτικότερο.
                item_rows = [(order_id, product_id, quantity) for product_id, quantity, _ in items]
                cur.executemany(SQL.INSERT_ORDER_ITEM, item_rows)
            return True, f"Η παραγγελία #{order_id} στάλθηκε."
        except mysql.connector.Error as exc:
            return False, f"Σφάλμα βάσης: {exc.msg}"

    @staticmethod
    def fetch_history(username, status_filter=None):
        """Φέρνει ιστορικό παραγγελιών και ομαδοποιεί προϊόντα ανά παραγγελία."""
        status_db = _normalize_status_filter(status_filter)
        if status_db:
            orders = Database.fetch_all(SQL.ORDER_HISTORY_BY_STATUS, (username, status_db))
        else:
            orders = Database.fetch_all(SQL.ORDER_HISTORY, (username,))
        if not orders:
            return []

        order_ids = [o["order_id"] for o in orders]
        grouped = _group_order_items(order_ids)

        for order in orders:
            order["items"] = grouped.get(order["order_id"], [])
            base_status = order.get("katastasi")
            shipment_status = order.get("shipment_status")
            display_status = base_status
            if base_status == ORDER_STATUS_TO_DB.get("Απεστάλη") and shipment_status:
                display_status = shipment_status
            if display_status in SHIPMENT_STATUS_LABELS:
                order["katastasi"] = SHIPMENT_STATUS_LABELS[display_status]
            else:
                order["katastasi"] = ORDER_STATUS_FROM_DB.get(display_status, display_status)
        return orders


class WarehouseRepository:
    """Λειτουργίες αποθήκης: παραγγελίες φαρμακείων, αποστολές και προμήθειες."""

    SUPPLIER_STORAGE_LABEL = "SUPPLIER_ORDERS_VIRTUAL"
    AUTO_SUPPLIER_NAME = "AUTO_SUPPLIER"
    AUTO_SUPPLIER_DEFAULT_PHONE = "2100000000"

    @staticmethod
    def fetch_pharmacy_orders(status_filter=None):
        """Φιλτράρει τις παραγγελίες ανά κατάσταση και συσχετίζει γραμμές με προϊόντα."""
        status_db = _normalize_status_filter(status_filter)
        if status_db:
            orders = Database.fetch_all(SQL.WAREHOUSE_ORDERS_BY_STATUS, (status_db,))
        else:
            orders = Database.fetch_all(SQL.WAREHOUSE_ORDERS)
        if not orders:
            return []

        # Φέρνουμε όλα τα order_ids ώστε να επαναχρησιμοποιήσουμε το group helper για τα προϊόντα.
        order_ids = [o["order_id"] for o in orders]
        grouped = _group_order_items(order_ids)

        for order in orders:
            # Εμπλουτίζουμε κάθε παραγγελία με τις γραμμές της και μεταφράζουμε την κατάσταση.
            order["items"] = grouped.get(order["order_id"], [])
            status = order.get("katastasi")
            order["katastasi"] = ORDER_STATUS_FROM_DB.get(status, status)
        return orders

    @staticmethod
    def update_order_status(order_id, new_status):
        """Ελέγχει αν η παραγγελία μπορεί να αλλάξει στάδιο ή χρειάζεται αποστολή."""
        normalized = ORDER_STATUS_TO_DB.get(new_status, new_status)
        if isinstance(normalized, str):
            normalized = normalized.upper()
        if normalized == ORDER_STATUS_TO_DB.get("Απεστάλη"):
            return WarehouseRepository.send_order(order_id)
        with Database.transaction(dictionary=True) as cur:
            cur.execute(SQL.ORDER_STATUS_BY_ID, (order_id,))
            order_row = cur.fetchone()
            if not order_row:
                return False, "Η παραγγελία δεν βρέθηκε."

            existing_shipment = WarehouseRepository._order_has_shipment(cur, order_id)
            if existing_shipment and order_row["katastasi"] != normalized:
                return False, "Η παραγγελία έχει ήδη αποστολή και δεν μπορεί να αλλάξει κατάσταση."

            cur.execute(SQL.UPDATE_ORDER_STATUS, (normalized, order_id))
            message = f"Η παραγγελία {order_id} άλλαξε σε '{new_status}'."
        return True, message

    @staticmethod
    def send_order(order_id):
        """Δημιουργεί αποστολή και μειώνει το διαθέσιμο στοκ ανά θέση αποθήκης."""
        with Database.transaction(dictionary=True) as cur:
            # 1. Φορτώνουμε την κεφαλίδα παραγγελίας για να ξέρουμε τρέχουσα κατάσταση/έκπτωση.
            cur.execute(SQL.ORDER_DETAILS_FOR_SHIPMENT, (order_id,))
            order_row = cur.fetchone()
            if not order_row:
                return False, "Η παραγγελία δεν βρέθηκε."
            if WarehouseRepository._order_has_shipment(cur, order_id):
                return False, "Υπάρχει ήδη αποστολή για την παραγγελία."

            # 2. Παίρνουμε τις γραμμές προϊόντων ώστε να επεξεργαστούμε κάθε SKU.
            items = WarehouseRepository._get_order_items(cur, order_id)
            if not items:
                return False, "Δεν μπορείτε να αποστείλετε παραγγελία χωρίς προϊόντα."

            shipped = []
            all_fulfilled = True
            total_cost_base = 0
            discount_percent = float(order_row.get("ekptosi") or 0)

            for item in items:
                # Για κάθε προϊόν εξαντλούμε σταδιακά τις θέσεις αποθήκης (FIFO ανά θέση).
                product_id = item["product_id"]
                requested = int(item["temaxia_zitisis"])
                unit_price = float(item["arx_kostos_temaxiou"])
                remaining = requested
                shipped_qty = 0

                # Φέρνουμε τις διαθέσιμες θέσεις για το συγκεκριμένο προϊόν ταξινομημένες.
                cur.execute(SQL.PRODUCT_LOCATIONS, (product_id,))
                locations = cur.fetchall()

                for loc in locations:
                    # Εφόσον ικανοποιήθηκε η ποσότητα προχωράμε στο επόμενο προϊόν.
                    if remaining <= 0:
                        break
                    available = int(loc["qty_in_stock"] or 0)
                    if available <= 0:
                        continue
                    # Παίρνουμε όσες μονάδες επιτρέπουν τα διαθέσιμα της θέσης.
                    take = min(available, remaining)
                    new_qty = available - take
                    if new_qty > 0:
                        # Εάν μένει υπόλοιπο, απλώς ενημερώνουμε το qty της θέσης.
                        cur.execute(
                            SQL.UPDATE_STOCK,
                            (
                                new_qty,
                                product_id,
                                loc["storage_id"],
                                loc["ar_diadromou"],
                                loc["ar_rafiou"],
                            ),
                        )
                    else:
                        # Διαφορετικά, διαγράφουμε τη γραμμή για να αδειάσει η θέση.
                        cur.execute(
                            SQL.DELETE_STOCK,
                            (
                                product_id,
                                loc["storage_id"],
                                loc["ar_diadromou"],
                                loc["ar_rafiou"],
                            ),
                        )
                    shipped_qty += take
                    remaining -= take

                if shipped_qty > 0:
                    # Προσθέτουμε τις αποσταλείσες μονάδες για υπολογισμό κόστους.
                    total_cost_base += shipped_qty * unit_price
                    shipped.append(
                        {
                            "product_id": product_id,
                            "temaxia_zitisis": shipped_qty,
                        }
                    )
                if remaining > 0:
                    all_fulfilled = False

            if not shipped:
                return False, "Δεν υπάρχει διαθέσιμο απόθεμα για αποστολή."

            # Κατάσταση αποστολής ανάλογα με το αν ικανοποιήθηκε πλήρως η ζήτηση.
            shipment_status = "ΟΛΟΚΛΗΡΩΜΕΝΗ" if all_fulfilled else "ΜΕΡΙΚΗ"
            # Το τελικό κόστος υπολογίζεται από τη συνολική αξία μείον την έκπτωση της παραγγελίας.
            total_cost = max(0.0, total_cost_base * (1 - discount_percent / 100))
            # Δημιουργούμε αποστολή και περνάμε τις γραμμές της αποστολής.
            WarehouseRepository._create_shipment(cur, order_id, total_cost, shipment_status, shipped)
            shipped_status = ORDER_STATUS_TO_DB.get("Απεστάλη", "ΑΠΕΣΤΑΛΕΙ")
            cur.execute(SQL.UPDATE_ORDER_STATUS, (shipped_status, order_id))
        return True, "Η παραγγελία αποστάλθηκε."

    @staticmethod
    def fetch_supplier_products():
        """Επιστρέφει λίστα προϊόντων όπως θα εμφανιστεί στην προμήθεια αποθήκης."""
        return Database.fetch_all(SQL.SUPPLIER_PRODUCTS)

    @staticmethod
    def create_supplier_order(items):
        """Αποθηκεύει παραγγελία προς προμηθευτές στο BACKORDER ώστε να υπάρχει μόνο στη MySQL."""
        if not items:
            return False, "Δεν προστέθηκαν προϊόντα."

        prepared = []
        for product_id, quantity, unit_price in items:
            try:
                product_id = int(product_id)
                quantity = int(quantity)
                unit_price = float(unit_price)
            except (TypeError, ValueError):
                continue
            if quantity <= 0 or unit_price <= 0:
                continue
            prepared.append(
                {
                    "product_id": product_id,
                    "quantity": quantity,
                    "unit_price": unit_price,
                }
            )
        if not prepared:
            return False, "Δεν προστέθηκαν προϊόντα."

        try:
            with Database.transaction(dictionary=True) as cur:
                supplier_storage_id = WarehouseRepository._ensure_supplier_storage(cur)
                cur.execute(
                    SQL.INSERT_BACKORDER,
                    (supplier_storage_id, 0, datetime.utcnow().date()),
                )
                backorder_id = cur.lastrowid
                for item in prepared:
                    supplier_id = WarehouseRepository._create_auto_supplier(cur)
                    cur.execute(
                        SQL.INSERT_SUPPLIER_BACKORDER_ITEM,
                        (supplier_id, item["product_id"], backorder_id, item["quantity"]),
                    )
            return True, backorder_id
        except mysql.connector.Error as exc:
            return False, f"Σφάλμα βάσης: {exc.msg}"

    @staticmethod
    def fetch_supplier_orders(status_filter=None):
        """Φορτώνει παραγγελίες προμηθευτών από τα BACKORDER entries με ειδική storage_id."""
        storage_id = WarehouseRepository._get_supplier_storage_id()
        if not storage_id:
            return []
        rows = Database.fetch_all(SQL.SUPPLIER_BACKORDERS, (storage_id,))
        if not rows:
            return []

        normalized = (status_filter or "Όλες").strip()
        status_lookup = {"Σε εξέλιξη": 0, "Ολοκληρώθηκε": 1}
        target = status_lookup.get(normalized)
        filtered = [row for row in rows if target is None or row["oloklirothike"] == target]
        if not filtered:
            return []

        order_ids = [row["backorder_id"] for row in filtered]
        items_map = WarehouseRepository._fetch_supplier_items(order_ids)

        orders = []
        for row in filtered:
            order_items = items_map.get(row["backorder_id"], [])
            total_cost = sum(item["quantity"] * item["unit_price"] for item in order_items)
            created_at = row.get("hm_apostolis")
            if created_at and not isinstance(created_at, datetime):
                created_at = datetime.combine(created_at, datetime.min.time())
            orders.append(
                {
                    "supplier_order_id": row["backorder_id"],
                    "created_at": created_at,
                    "total_cost": total_cost,
                    "status": "Ολοκληρώθηκε" if row["oloklirothike"] else "Σε εξέλιξη",
                    "items": order_items,
                }
            )
        return orders

    @staticmethod
    def mark_supplier_order_complete(order_id):
        """Μόλις παραδοθεί παραγγελία προμηθευτή, ενημερώνει θέσεις και καταγράφει backorders."""
        storage_id = WarehouseRepository._get_supplier_storage_id()
        if not storage_id:
            return False, "Δεν υπάρχει καταχωρημένη παραγγελία."
        order_row = Database.fetch_one(SQL.SUPPLIER_BACKORDER_BY_ID, (order_id,))
        if not order_row or order_row.get("storage_id") != storage_id:
            return False, "Η παραγγελία δεν υπάρχει."
        if order_row.get("oloklirothike"):
            return False, "Η παραγγελία έχει ήδη ολοκληρωθεί."

        items_map = WarehouseRepository._fetch_supplier_items([order_id])
        items = items_map.get(order_id) or []
        if not items:
            return False, "Δεν βρέθηκαν προϊόντα για την παραγγελία."

        with Database.transaction(dictionary=True) as cur:
            storage_ids = set()
            for item in items:
                # Για κάθε προϊόν της παραλαβής βρίσκουμε σε ποια θέση θα τοποθετηθεί.
                storage_id = WarehouseRepository._assign_product_to_position(
                    cur, item["product_id"], item["quantity"]
                )
                if storage_id:
                    storage_ids.add(storage_id)

            executed_at = datetime.now()
            for storage_id in storage_ids:
                # Από τη στιγμή που γεμίσαμε μια θέση, ενημερώνουμε τα backorders.
                WarehouseRepository._record_backorder(cur, storage_id, executed_at)
            cur.execute(
                SQL.UPDATE_BACKORDER_STATUS,
                (1, executed_at.date(), order_id),
            )

        return True, "Η παραγγελία ολοκληρώθηκε."

    @staticmethod
    def _order_has_shipment(cur, order_id):
        """Ελέγχει αν έχει ήδη δημιουργηθεί αποστολή για την παραγγελία."""
        cur.execute(SQL.ORDER_HAS_SHIPMENT, (order_id,))
        return cur.fetchone() is not None

    @staticmethod
    def _get_order_items(cur, order_id):
        """Φέρνει τα προϊόντα μιας παραγγελίας μέσα σε ανοιχτή συναλλαγή."""
        cur.execute(SQL.ORDER_ITEMS_SIMPLE, (order_id,))
        rows = cur.fetchall()
        return rows or []

    @staticmethod
    def _calculate_shipment_status(items, available_map):
        """Υπολογίζει αν η αποστολή θα είναι μερική ή πλήρης με βάση το διαθέσιμο."""
        if not items:
            return "ΟΛΟΚΛΗΡΩΜΕΝΗ"
        for item in items:
            qty = int(item["temaxia_zitisis"] or 0)
            available = int(available_map.get(item["product_id"], 0))
            if available < qty:
                return "ΜΕΡΙΚΗ"
        return "ΟΛΟΚΛΗΡΩΜΕΝΗ"

    @staticmethod
    def _create_shipment(cur, order_id, total_cost, shipment_status, items):
        """Καταγράφει νέα αποστολή και τις αντίστοιχες γραμμές σε μια συναλλαγή."""
        status_db = shipment_status.upper() if isinstance(shipment_status, str) else shipment_status
        cur.execute(
            SQL.INSERT_SHIPMENT,
            (random.randint(100, 999), status_db, datetime.now(), total_cost, order_id),
        )
        shipment_id = cur.lastrowid
        item_rows = [
            (shipment_id, item["product_id"], item["temaxia_zitisis"]) for item in items
        ]
        cur.executemany(SQL.INSERT_SHIPMENT_ITEM, item_rows)
        return shipment_id

    @staticmethod
    def _get_supplier_storage_id():
        row = Database.fetch_one(SQL.SUPPLIER_STORAGE_BY_LABEL, (WarehouseRepository.SUPPLIER_STORAGE_LABEL,))
        return row["storage_id"] if row else None

    @staticmethod
    def _ensure_supplier_storage(cur):
        cur.execute(SQL.SUPPLIER_STORAGE_BY_LABEL, (WarehouseRepository.SUPPLIER_STORAGE_LABEL,))
        row = cur.fetchone()
        if row:
            return row["storage_id"]
        cur.execute(SQL.NEXT_STORAGE_ID)
        storage_id = cur.fetchone()["next_id"]
        cur.execute(SQL.INSERT_STORAGE, (storage_id, WarehouseRepository.SUPPLIER_STORAGE_LABEL))
        return storage_id

    @staticmethod
    def _create_auto_supplier(cur):
        """Δημιουργεί εγγραφή προμηθευτή placeholder με προκαθορισμένο τηλέφωνο."""
        cur.execute(SQL.INSERT_SUPPLIER, (WarehouseRepository.AUTO_SUPPLIER_NAME, WarehouseRepository.AUTO_SUPPLIER_DEFAULT_PHONE))
        return cur.lastrowid

    @staticmethod
    def _fetch_supplier_items(order_ids):
        """Φέρνει τα προϊόντα των προμηθευτικών παραγγελιών από τις γέφυρες backorder/supplier."""
        if not order_ids:
            return {}
        query = with_in_clause(SQL.SUPPLIER_BACKORDER_ITEMS, order_ids)
        rows = Database.fetch_all(query, order_ids)
        grouped = defaultdict(list)
        for row in rows:
            quantity = max(1, int(row.get("quantity") or 0))
            grouped[row["backorder_id"]].append(
                {
                    "product_id": row["product_id"],
                    "onoma": row["onoma"],
                    "quantity": quantity,
                    "unit_price": float(row["arx_kostos_temaxiou"]),
                }
            )
        return grouped

    @staticmethod
    def _assign_product_to_position(cur, product_id, quantity):
        """Τοποθετεί την παραλαβή σε υπάρχουσα θέση ή δημιουργεί νέα θέση αποθήκης."""
        if quantity <= 0:
            return None

        # Προσπαθούμε πρώτα να ενισχύσουμε την «καλύτερη» θέση του προϊόντος (περισσότερο στοκ).
        cur.execute(SQL.BEST_PRODUCT_POSITION, (product_id,))
        best_slot = cur.fetchone()
        if best_slot:
            # Ενημερώνουμε την υπάρχουσα θέση με προσθετική ενημέρωση qty_in_stock.
            cur.execute(
                SQL.UPDATE_POSITION_STOCK,
                (
                    quantity,
                    product_id,
                    best_slot["storage_id"],
                    best_slot["ar_diadromou"],
                    best_slot["ar_rafiou"],
                ),
            )
            return best_slot["storage_id"]

        # Αν δεν υπάρχει καμία θέση για το προϊόν, βρίσκουμε ή δημιουργούμε νέα κενή τοποθεσία.
        slot = WarehouseRepository._ensure_empty_position(cur)
        cur.execute(
            SQL.INSERT_POSITION_STOCK,
            (
                product_id,
                slot["storage_id"],
                slot["ar_diadromou"],
                slot["ar_rafiou"],
                quantity,
            ),
        )
        return slot["storage_id"]

    @staticmethod
    def _ensure_empty_position(cur):
        """Βρίσκει κενή θέση αποθήκης ή δημιουργεί καινούρια όταν δεν υπάρχουν."""
        cur.execute(SQL.AVAILABLE_POSITIONS)
        slot = cur.fetchone()
        if slot:
            return slot

        cur.execute(SQL.NEXT_STORAGE_ID)
        storage_id = cur.fetchone()["next_id"]
        # Δημιουργούμε νέα εγγραφή αποθήκης ώστε να φιλοξενήσει τις μελλοντικές θέσεις.
        cur.execute(SQL.INSERT_STORAGE, (storage_id, f"Αποθήκη #{storage_id}"))

        cur.execute(SQL.NEXT_AISLE)
        aisle = cur.fetchone()["next_aisle"]
        shelf = 1
        # Προσθέτουμε καινούριο διάδρομο/ράφι και τον αντιστοιχούμε στην αποθήκη.
        cur.execute(SQL.INSERT_THESI, (aisle, shelf))
        cur.execute(SQL.INSERT_THESI_BRISKETAI, (storage_id, aisle, shelf))
        return {"storage_id": storage_id, "ar_diadromou": aisle, "ar_rafiou": shelf}

    @staticmethod
    def _record_backorder(cur, storage_id, executed_at):
        """Καταγράφει στο BACKORDER ότι η συγκεκριμένη αποθήκη εξυπηρετήθηκε την ημερομηνία παραλαβής."""
        if not storage_id:
            return
        # Το hm_apostolis αναμένει ημερομηνία, οπότε χρησιμοποιούμε date() αν το input είναι datetime.
        cur.execute(
            SQL.INSERT_BACKORDER,
            (
                storage_id,
                1,
                (executed_at.date() if hasattr(executed_at, "date") else executed_at),
            ),
        )


__all__ = [
    "AuthManager",
    "InventoryRepository",
    "PharmacyRepository",
    "WarehouseRepository",
    "calculate_delivery_days",
    "calculate_delivery_eta",
    "format_delivery_remaining",
    "CONTRACT_DURATION_CHOICES",
    "CONTRACT_DURATION_LOOKUP",
    "DISCOUNT_BY_MONTHS",
]
