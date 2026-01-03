"""Στρώμα πρόσβασης σε MySQL (connection pool, helpers, SQL σταθερές)."""

import os
import ssl
from contextlib import contextmanager

import mysql.connector
from dotenv import load_dotenv
from mysql.connector.pooling import MySQLConnectionPool

# Φορτώνουμε τις μεταβλητές περιβάλλοντος από αρχείο .env (αν υπάρχει).
load_dotenv()

# Προσαρμογή του wrap_socket για νέες εκδόσεις Python όταν απαιτείται.
if not hasattr(ssl, "wrap_socket"):

    def _compat_wrap_socket(
        sock,
        keyfile=None,
        certfile=None,
        server_side=False,
        cert_reqs=ssl.CERT_NONE,
        ssl_version=getattr(ssl, "PROTOCOL_TLS_CLIENT", ssl.PROTOCOL_TLS),
        ca_certs=None,
        do_handshake_on_connect=True,
        suppress_ragged_eofs=True,
        server_hostname=None,
        **kwargs,
    ):
        """Fallback για περιβάλλοντα χωρίς ssl.wrap_socket."""
        context = ssl.SSLContext(ssl_version)
        context.check_hostname = server_hostname is not None
        context.verify_mode = cert_reqs
        if certfile or keyfile:
            context.load_cert_chain(certfile, keyfile)
        if ca_certs:
            context.load_verify_locations(ca_certs)
        return context.wrap_socket(
            sock,
            server_side=server_side,
            do_handshake_on_connect=do_handshake_on_connect,
            suppress_ragged_eofs=suppress_ragged_eofs,
            server_hostname=server_hostname,
        )

    ssl.wrap_socket = _compat_wrap_socket


def _in_clause(count):
    """Επιστρέφει placeholders τύπου %s,%s,... για IN clauses."""
    return ",".join(["%s"] * count)


def with_in_clause(sql_template, values):
    """Κάνει format σε query με δυναμικό πλήθος placeholders (χρήσιμο για IN ...)."""
    if not values:
        raise ValueError("Values are required for IN clause formatting.")
    return sql_template.format(placeholders=_in_clause(len(values)))


class Database:
    """Βοηθητική κλάση για συνδέσεις MySQL με pool και συναλλαγές."""

    _pool = None

    @staticmethod
    def _config():
        # Διαβάζουμε ρυθμίσεις από μεταβλητές περιβάλλοντος (φορτώνονται μέσω .env).
        return {
            "host": os.getenv("DB_HOST", "127.0.0.1"),
            "user": os.getenv("DB_USER", "admin"),
            "password": os.getenv("DB_PASSWORD", "password"),
            "database": os.getenv("DB_NAME", "farmakeio_db"),
            "port": int(os.getenv("DB_PORT", "3306")),
        }

    @classmethod
    def _get_pool(cls):
        """Δημιουργεί ( μία φορά ) το connection pool ώστε να επαναχρησιμοποιούνται συνδέσεις."""
        if cls._pool is None:
            pool_size = int(os.getenv("DB_POOL_SIZE", "5"))
            cls._pool = MySQLConnectionPool(
                pool_name="farmakeio_pool",
                pool_size=max(1, pool_size),
                pool_reset_session=True,
                **cls._config(),
            )
        return cls._pool

    @classmethod
    @contextmanager
    def connect(cls):
        """Επιστρέφει context manager με ανοιχτή σύνδεση (fallback χωρίς pool αν αποτύχει)."""
        try:
            conn = cls._get_pool().get_connection()
        except mysql.connector.Error:
            conn = mysql.connector.connect(**cls._config())
        try:
            yield conn
        finally:
            conn.close()

    @classmethod
    @contextmanager
    def cursor(cls, *, dictionary=True):
        """Δίνει cursor με αυτόματο κλείσιμο όταν τελειώσει το context."""
        with cls.connect() as conn:
            cur = conn.cursor(dictionary=dictionary)
            try:
                yield cur
            finally:
                cur.close()

    @classmethod
    @contextmanager
    def transaction(cls, *, dictionary=True):
        """Εκτελεί block με αυτόματο commit/rollback (χρήσιμο για πολλαπλές εντολές)."""
        with cls.connect() as conn:
            cur = conn.cursor(dictionary=dictionary)
            try:
                yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()

    @classmethod
    def fetch_all(cls, query, params=None):
        """Εκτελεί SELECT που επιστρέφει λίστες εγγραφών (ή κενή λίστα)."""
        with cls.cursor(dictionary=True) as cur:
            cur.execute(query, params or ())
            return cur.fetchall() or []

    @classmethod
    def fetch_one(cls, query, params=None):
        """Εκτελεί SELECT που περιμένει μοναδικό αποτέλεσμα."""
        with cls.cursor(dictionary=True) as cur:
            cur.execute(query, params or ())
            return cur.fetchone()


class SQL:
    """Σταθερές SQL εντολών για αποφυγή διαρροής κειμένων σε άλλα modules."""

    # Επιστρέφει τη διαθεσιμότητα αποθέματος για συγκεκριμένα product_ids.
    INVENTORY_AVAILABLE_BY_IDS = """
        SELECT product_id, COALESCE(SUM(qty_in_stock), 0) AS available
        FROM PROION_YPARXEI_APOTHIKI_THESI
        WHERE product_id IN ({placeholders})
        GROUP BY product_id
    """
    # Όλη η αποθήκη συγκεντρωτικά για κάθε προϊόν (για γρήγορη εικόνα αποθεμάτων).
    INVENTORY_ALL_STOCK = """
        SELECT product_id, COALESCE(SUM(qty_in_stock), 0) AS available
        FROM PROION_YPARXEI_APOTHIKI_THESI
        GROUP BY product_id
    """

    # USER_EXISTS: γρήγορος έλεγχος ύπαρξης username (χρησιμοποιείται στην εγγραφή).
    USER_EXISTS = "SELECT 1 FROM XRISTIS WHERE username = %s"
    # PHARMACY_AFM_EXISTS: διασφαλίζει ότι ένα ΑΦΜ δεν έχει δηλωθεί από άλλο φαρμακείο.
    PHARMACY_AFM_EXISTS = "SELECT 1 FROM FARMAKEIO WHERE afm = %s"
    INSERT_USER = (
        "INSERT INTO XRISTIS (username, onomateponumo, hashed_password, tilefono) "
        "VALUES (%s,%s,%s,%s)"
    )
    # INSERT_STAFF/INSERT_PHARMACY: γράφουν τα στοιχεία ρόλου μετά τη δημιουργία XRISTIS.
    INSERT_STAFF = "INSERT INTO PROSOPIKO (username) VALUES (%s)"
    INSERT_PHARMACY = "INSERT INTO FARMAKEIO (username, afm, topothesia) VALUES (%s,%s,%s)"
    # LOGIN_WITH_ROLE: φέρνει το hashed password και εντοπίζει αν ο χρήστης είναι φαρμακείο ή προσωπικό.
    LOGIN_WITH_ROLE = """
        SELECT x.username,
               x.hashed_password,
               f.username AS pharmacy_username,
               p.username AS staff_username
        FROM XRISTIS x
        LEFT JOIN FARMAKEIO f ON f.username = x.username
        LEFT JOIN PROSOPIKO p ON p.username = x.username
        WHERE x.username = %s
    """

    # PHARMACY_PRODUCTS: επιστρέφει το master list προϊόντων μαζί με συνολικό stock (join με αποθήκη).
    PHARMACY_PRODUCTS = """
        SELECT p.product_id,
               p.onoma,
               p.katigoria,
               p.arx_kostos_temaxiou,
               p.etairia,
               p.periektikotita,
               COALESCE(SUM(s.qty_in_stock), 0) AS stock_qty
        FROM PROION p
        LEFT JOIN PROION_YPARXEI_APOTHIKI_THESI s ON s.product_id = p.product_id
        GROUP BY p.product_id, p.onoma, p.katigoria, p.arx_kostos_temaxiou, p.etairia, p.periektikotita
        ORDER BY p.onoma
    """
    # PHARMACY_AFM: παίρνει το ΑΦΜ του φαρμακείου με βάση το username του XRISTIS.
    PHARMACY_AFM = "SELECT afm FROM FARMAKEIO WHERE username = %s"
    # PHARMACY_CONTRACTS: φέρνει όλα τα συμβόλαια ενός φαρμακείου ταξινομημένα με πιο πρόσφατη υπογραφή.
    PHARMACY_CONTRACTS = """
        SELECT s.agreement_id,
               s.suxnotita_paradosis,
               s.tropos_pliromis,
               s.hm_ypografis,
               s.hm_liksis,
               s.diarkeia_mhnwn
        FROM SYMBOLAIO s
        JOIN FARMAKEIO f ON f.afm = s.afm_farmakeiou
        WHERE f.username = %s
        ORDER BY s.hm_ypografis DESC
    """
    # ACTIVE_CONTRACT: ελέγχει αν υπάρχει ενεργό συμβόλαιο που δεν έχει λήξει (hm_liksis > σήμερα).
    ACTIVE_CONTRACT = """
        SELECT s.agreement_id
        FROM SYMBOLAIO s
        JOIN FARMAKEIO f ON f.afm = s.afm_farmakeiou
        WHERE f.username = %s AND s.hm_liksis > %s
        ORDER BY s.hm_ypografis DESC
        LIMIT 1
    """
    # INSERT_CONTRACT: δημιουργεί νέα εγγραφή στη SYMBOLAIO με όλες τις παραμέτρους της φόρμας.
    INSERT_CONTRACT = """
        INSERT INTO SYMBOLAIO (
            suxnotita_paradosis,
            tropos_pliromis,
            afm_farmakeiou,
            hm_ypografis,
            hm_liksis,
            diarkeia_mhnwn
        )
        VALUES (%s,%s,%s,%s,%s,%s)
    """
    # CANCEL_CONTRACT: απλώς ενημερώνει την hm_liksis ώστε να θεωρηθεί λήξαν το συμβόλαιο.
    CANCEL_CONTRACT = "UPDATE SYMBOLAIO SET hm_liksis = %s WHERE agreement_id = %s"
    # PRODUCT_PRICES_BY_IDS: helper για τιμές αγοράς πολλών προϊόντων (χρησιμοποιεί IN clause).
    PRODUCT_PRICES_BY_IDS = """
        SELECT product_id, arx_kostos_temaxiou
        FROM PROION
        WHERE product_id IN ({placeholders})
    """
    # PRODUCT_NAMES_BY_IDS: παίρνει τα ονόματα ώστε να εμπλουτίσουμε JSON παραγγελίες προμηθευτή.
    PRODUCT_NAMES_BY_IDS = """
        SELECT product_id, onoma
        FROM PROION
        WHERE product_id IN ({placeholders})
    """
    # INSERT_ORDER: δημιουργεί την κεφαλίδα παραγγελίας (κατάσταση, κόστος, έκπτωση, αφμ, timestamp).
    INSERT_ORDER = """
        INSERT INTO PARAGGELIA (katastasi, arxiko_kostos, ekptosi, afm_farmakeiou, hm_ora_ektelesis)
        VALUES (%s,%s,%s,%s,%s)
    """
    # INSERT_ORDER_ITEM: προσθέτει γραμμές προϊόντων στην παραγγελία.
    INSERT_ORDER_ITEM = """
        INSERT INTO PARAGGELEIA_PERIEXEI_PROION (order_id, product_id, temaxia_zitisis)
        VALUES (%s,%s,%s)
    """
    # ORDER_HISTORY: φέρνει όλες τις παραγγελίες φαρμακείου και κάνει LEFT JOIN με max(hm_ora_apostolis)
    # ώστε να εμφανίζεται η τελευταία αποστολή (αν υπάρχει). Η υποερώτηση ship ομαδοποιεί ανά order_id.
    ORDER_HISTORY = """
        SELECT p.order_id,
               p.hm_ora_ektelesis AS executed_at,
               p.katastasi,
               p.arxiko_kostos,
               ship.hm_ora_apostolis AS shipment_at,
               ship.katastasi AS shipment_status
        FROM PARAGGELIA p
        JOIN FARMAKEIO f ON f.afm = p.afm_farmakeiou
        LEFT JOIN (
            SELECT latest.order_id,
                   a.hm_ora_apostolis,
                   a.katastasi
            FROM APOSTOLI a
            JOIN (
                SELECT order_id, MAX(hm_ora_apostolis) AS hm_ora_apostolis
                FROM APOSTOLI
                GROUP BY order_id
            ) latest
              ON latest.order_id = a.order_id
             AND latest.hm_ora_apostolis = a.hm_ora_apostolis
        ) ship ON ship.order_id = p.order_id
        WHERE f.username = %s
        ORDER BY p.hm_ora_ektelesis DESC
    """
    # ORDER_HISTORY_BY_STATUS: ίδιο με παραπάνω αλλά προσθέτει φίλτρο κατάστασης p.katastasi = %s.
    ORDER_HISTORY_BY_STATUS = """
        SELECT p.order_id,
               p.hm_ora_ektelesis AS executed_at,
               p.katastasi,
               p.arxiko_kostos,
               ship.hm_ora_apostolis AS shipment_at,
               ship.katastasi AS shipment_status
        FROM PARAGGELIA p
        JOIN FARMAKEIO f ON f.afm = p.afm_farmakeiou
        LEFT JOIN (
            SELECT latest.order_id,
                   a.hm_ora_apostolis,
                   a.katastasi
            FROM APOSTOLI a
            JOIN (
                SELECT order_id, MAX(hm_ora_apostolis) AS hm_ora_apostolis
                FROM APOSTOLI
                GROUP BY order_id
            ) latest
              ON latest.order_id = a.order_id
             AND latest.hm_ora_apostolis = a.hm_ora_apostolis
        ) ship ON ship.order_id = p.order_id
        WHERE f.username = %s AND p.katastasi = %s
        ORDER BY p.hm_ora_ektelesis DESC
    """
    # ORDER_ITEMS_WITH_STOCK: περιγράφει τις γραμμές μιας παραγγελίας μαζί με διαθέσιμο stock και shipped qty.
    # Η εσωτερική ship subquery αφαιρείται ανά order_id/product και επιστρέφει sum των αποσταλμένων τεμαχίων.
    ORDER_ITEMS_WITH_STOCK = """
        SELECT i.order_id,
               i.product_id,
               pr.onoma,
               i.temaxia_zitisis,
               pr.arx_kostos_temaxiou,
               COALESCE(SUM(stock.qty_in_stock), 0) AS available,
               COALESCE(shipments.shipped_qty, 0) AS shipped_qty
        FROM PARAGGELEIA_PERIEXEI_PROION i
        JOIN PROION pr ON pr.product_id = i.product_id
        LEFT JOIN PROION_YPARXEI_APOTHIKI_THESI stock ON stock.product_id = i.product_id
        LEFT JOIN (
            SELECT a.order_id, ap.product_id, SUM(ap.temaxia_apostolis) AS shipped_qty
            FROM APOSTOLI_PERIEXEI_PROION ap
            JOIN APOSTOLI a ON a.shipment_id = ap.shipment_id
            WHERE a.order_id IN ({placeholders})
            GROUP BY a.order_id, ap.product_id
        ) shipments ON shipments.order_id = i.order_id AND shipments.product_id = i.product_id
        WHERE i.order_id IN ({placeholders})
        GROUP BY i.order_id,
                 i.product_id,
                 pr.onoma,
                 i.temaxia_zitisis,
                 pr.arx_kostos_temaxiou,
                 shipments.shipped_qty
    """

    # WAREHOUSE_ORDERS: δίνει στο προσωπικό αποθήκης όλες τις παραγγελίες μαζί με username φαρμακείου.
    WAREHOUSE_ORDERS = """
        SELECT p.order_id, x.username AS pharmacy, p.hm_ora_ektelesis AS executed_at,
               p.katastasi, p.arxiko_kostos
        FROM PARAGGELIA p
        JOIN FARMAKEIO f ON f.afm = p.afm_farmakeiou
        JOIN XRISTIS x ON x.username = f.username
        ORDER BY p.hm_ora_ektelesis DESC
    """
    # WAREHOUSE_ORDERS_BY_STATUS: έκδοση με φίλτρο κατάστασης για την οθόνη filters.
    WAREHOUSE_ORDERS_BY_STATUS = """
        SELECT p.order_id, x.username AS pharmacy, p.hm_ora_ektelesis AS executed_at,
               p.katastasi, p.arxiko_kostos
        FROM PARAGGELIA p
        JOIN FARMAKEIO f ON f.afm = p.afm_farmakeiou
        JOIN XRISTIS x ON x.username = f.username
        WHERE p.katastasi = %s
        ORDER BY p.hm_ora_ektelesis DESC
    """
    # ORDER_STATUS_BY_ID: χρησιμοποιείται πριν από updates για να ελέγξουμε τρέχουσα κατάσταση/κόστος.
    ORDER_STATUS_BY_ID = "SELECT katastasi, arxiko_kostos FROM PARAGGELIA WHERE order_id = %s"
    # UPDATE_ORDER_STATUS: ενημερώνει μόνο το πεδίο katastasi.
    UPDATE_ORDER_STATUS = "UPDATE PARAGGELIA SET katastasi = %s WHERE order_id = %s"
    # ORDER_DETAILS_FOR_SHIPMENT: επιστρέφει βασικά πεδία που χρειάζονται για τη δημιουργία αποστολής.
    ORDER_DETAILS_FOR_SHIPMENT = "SELECT katastasi, arxiko_kostos, ekptosi FROM PARAGGELIA WHERE order_id = %s"
    # ORDER_ITEMS_SIMPLE: χρησιμοποιείται στο picking για να έχουμε τις ζητούμενες ποσότητες/τιμές ανά προϊόν.
    ORDER_ITEMS_SIMPLE = """
        SELECT i.product_id, i.temaxia_zitisis, pr.arx_kostos_temaxiou, pr.onoma
        FROM PARAGGELEIA_PERIEXEI_PROION i
        JOIN PROION pr ON pr.product_id = i.product_id
        WHERE i.order_id = %s
    """
    # PRODUCT_LOCATIONS: επιστρέφει όλες τις θέσεις (storage/διάδρομος/ράφι) για ένα προϊόν ταξινομημένες,
    # ώστε ο αλγόριθμος αποστολής να εξαντλεί τις ποσότητες σειριακά.
    PRODUCT_LOCATIONS = """
        SELECT storage_id, ar_diadromou, ar_rafiou, qty_in_stock
        FROM PROION_YPARXEI_APOTHIKI_THESI
        WHERE product_id = %s
        ORDER BY storage_id, ar_diadromou, ar_rafiou
    """
    # UPDATE_STOCK: μειώνει το απόθεμα συγκεκριμένης θέσης (χρησιμοποιείται κατά τη διαδικασία picking).
    UPDATE_STOCK = """
        UPDATE PROION_YPARXEI_APOTHIKI_THESI
        SET qty_in_stock = %s
        WHERE product_id = %s AND storage_id = %s AND ar_diadromou = %s AND ar_rafiou = %s
    """
    # DELETE_STOCK: διαγράφει τη γραμμή όταν μια θέση αδειάσει πλήρως ώστε να μην κρατά «νεκρά» rows.
    DELETE_STOCK = """
        DELETE FROM PROION_YPARXEI_APOTHIKI_THESI
        WHERE product_id = %s AND storage_id = %s AND ar_diadromou = %s AND ar_rafiou = %s
    """

    # SUPPLIER_PRODUCTS: όμοιο με PHARMACY_PRODUCTS αλλά χρησιμοποιείται από την αποθήκη για προμήθειες.
    SUPPLIER_PRODUCTS = """
        SELECT p.product_id,
               p.onoma,
               p.arx_kostos_temaxiou,
               p.etairia,
               p.katigoria,
               COALESCE(SUM(s.qty_in_stock), 0) AS stock_qty
        FROM PROION p
        LEFT JOIN PROION_YPARXEI_APOTHIKI_THESI s ON s.product_id = p.product_id
        GROUP BY p.product_id, p.onoma, p.arx_kostos_temaxiou, p.etairia, p.katigoria
        ORDER BY p.onoma
    """
    # BEST_PRODUCT_POSITION: βρίσκει την πλουσιότερη θέση μιας SKU ώστε να προστεθεί εκεί νέο απόθεμα.
    BEST_PRODUCT_POSITION = """
        SELECT storage_id, ar_diadromou, ar_rafiou, qty_in_stock
        FROM PROION_YPARXEI_APOTHIKI_THESI
        WHERE product_id = %s
        ORDER BY qty_in_stock DESC
        LIMIT 1
    """
    # UPDATE_POSITION_STOCK: αυξάνει το qty μιας υπάρχουσας θέσης (χρησιμοποιείται μετά από παραλαβή).
    UPDATE_POSITION_STOCK = """
        UPDATE PROION_YPARXEI_APOTHIKI_THESI
        SET qty_in_stock = qty_in_stock + %s
        WHERE product_id = %s AND storage_id = %s AND ar_diadromou = %s AND ar_rafiou = %s
    """
    # INSERT_POSITION_STOCK: δημιουργεί νέα εγγραφή στη γέφυρα προϊόντος/θέσης (όταν δεν υπάρχει ήδη).
    INSERT_POSITION_STOCK = """
        INSERT INTO PROION_YPARXEI_APOTHIKI_THESI (product_id, storage_id, ar_diadromou, ar_rafiou, qty_in_stock)
        VALUES (%s,%s,%s,%s,%s)
    """
    # Helpers για δημιουργία καινούριων αποθηκών/διαδρόμων/ραφιών όταν εξαντληθούν οι διαθέσιμες θέσεις.
    STORAGE_IDS = "SELECT storage_id FROM APOTHIKI"
    NEXT_STORAGE_ID = "SELECT COALESCE(MAX(storage_id), 0) + 1 AS next_id FROM APOTHIKI"
    INSERT_STORAGE = "INSERT INTO APOTHIKI (storage_id, topothesia) VALUES (%s,%s)"
    STORAGE_HAS_POSITIONS = "SELECT 1 FROM THESI_BRISKETAI_APOTHIKI WHERE storage_id = %s LIMIT 1"
    NEXT_AISLE = "SELECT COALESCE(MAX(ar_diadromou), 0) + 1 AS next_aisle FROM THESI"
    INSERT_THESI = "INSERT INTO THESI (ar_diadromou, ar_rafiou) VALUES (%s,%s)"
    INSERT_THESI_BRISKETAI = """
        INSERT INTO THESI_BRISKETAI_APOTHIKI (storage_id, ar_diadromou, ar_rafiou)
        VALUES (%s,%s,%s)
    """
    # Θέσεις αποθήκης που δεν είναι πιασμένες από άλλο προϊόν (για νέα παρτίδα).
    AVAILABLE_POSITIONS = """
        SELECT t.storage_id, t.ar_diadromou, t.ar_rafiou
        FROM THESI_BRISKETAI_APOTHIKI t
        LEFT JOIN PROION_YPARXEI_APOTHIKI_THESI p
          ON p.storage_id = t.storage_id
         AND p.ar_diadromou = t.ar_diadromou
         AND p.ar_rafiou = t.ar_rafiou
        WHERE p.product_id IS NULL
        LIMIT 1
    """
    # INSERT_BACKORDER: αρχεία στο ιστορικό backorders πότε εξυπηρετήθηκε μια αποθήκη (oloklirothike flag).
    INSERT_BACKORDER = "INSERT INTO BACKORDER (storage_id, oloklirothike, hm_apostolis) VALUES (%s,%s,%s)"

    # ORDER_HAS_SHIPMENT: χρησιμεύει ως guard για να μη δημιουργηθεί δεύτερη αποστολή για την ίδια παραγγελία.
    ORDER_HAS_SHIPMENT = "SELECT shipment_id FROM APOSTOLI WHERE order_id = %s LIMIT 1"
    # INSERT_SHIPMENT: δημιουργεί την κεφαλίδα αποστολής (τυχαίο δρομολόγιο + κατάσταση + κόστος).
    INSERT_SHIPMENT = """
        INSERT INTO APOSTOLI (dromologio, katastasi, hm_ora_apostolis, teliko_kostos, order_id)
        VALUES (%s,%s,%s,%s,%s)
    """
    # INSERT_SHIPMENT_ITEM: συμπληρώνει τα προϊόντα που στάλθηκαν σε κάθε αποστολή.
    INSERT_SHIPMENT_ITEM = """
        INSERT INTO APOSTOLI_PERIEXEI_PROION (shipment_id, product_id, temaxia_apostolis)
        VALUES (%s,%s,%s)
    """

    # --- Καταγραφή παραγγελιών προμηθευτών μέσα από τα BACKORDER ---
    SUPPLIER_STORAGE_BY_LABEL = "SELECT storage_id FROM APOTHIKI WHERE topothesia = %s LIMIT 1"
    INSERT_SUPPLIER = "INSERT INTO PROMITHEYTIS (onoma, tilefono) VALUES (%s,%s)"
    INSERT_SUPPLIER_BACKORDER_ITEM = """
        INSERT INTO PROMITHEYTIS_APOSTELEI_PROION_BACKORDER (supplier_id, product_id, backorder_id, quantity)
        VALUES (%s,%s,%s,%s)
    """
    SUPPLIER_BACKORDERS = """
        SELECT backorder_id, storage_id, hm_apostolis, oloklirothike
        FROM BACKORDER
        WHERE storage_id = %s
        ORDER BY backorder_id DESC
    """
    SUPPLIER_BACKORDER_BY_ID = """
        SELECT backorder_id, storage_id, hm_apostolis, oloklirothike
        FROM BACKORDER
        WHERE backorder_id = %s
    """
    SUPPLIER_BACKORDER_ITEMS = """
        SELECT papb.backorder_id,
               papb.product_id,
               pr.onoma,
               pr.arx_kostos_temaxiou,
               sup.supplier_id,
               sup.tilefono,
               papb.quantity
        FROM PROMITHEYTIS_APOSTELEI_PROION_BACKORDER papb
        JOIN PROION pr ON pr.product_id = papb.product_id
        JOIN PROMITHEYTIS sup ON sup.supplier_id = papb.supplier_id
        WHERE papb.backorder_id IN ({placeholders})
    """
    UPDATE_BACKORDER_STATUS = "UPDATE BACKORDER SET oloklirothike = %s, hm_apostolis = %s WHERE backorder_id = %s"
