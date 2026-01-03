# farmakeio_db
Τελικό project Βάσεων Δεδομένων (7ο εξάμηνο 2025-2026, Ομάδα 1). Desktop εφαρμογή διαχείρισης παραγγελιών φαρμακείων με MySQL backend.

## Προαπαιτούμενα
- Python 3.10+.
- MySQL 8.x (ή συμβατή έκδοση).
- Το `tkinter` είναι μέρος της standard βιβλιοθήκης της Python (στα Windows/Linux πακέτα μπορεί να χρειαστεί ξεχωριστή εγκατάσταση).

## Εγκατάσταση
1. Κάνε clone ή κατέβασε το repository και κάντο αποσυμπίεση.
2. Από το root του project εγκατέστησε τις εξαρτήσεις:
   ```bash
   python3 -m pip install -r requirements.txt
   ```

## Ρύθμιση βάσης
Η εφαρμογή περιμένει βάση MySQL με όνομα `farmakeio_db` (μπορεί να αλλάξει μέσω .env).

1. Δημιούργησε το schema:
   ```bash
   mysql -u <user> -p < sql/schema.sql
   ```
2. Φόρτωσε δείγμα προϊόντων (χρειάζεται `LOCAL INFILE`):
   ```bash
   cd sql
   mysql --local-infile=1 -u <user> -p < proionta.sql
   ```
   Το αρχείο `sql/proionta.sql` διαβάζει το `sql/proion_brands.csv`.

## Περιβάλλον (.env)
Μπορείς να δημιουργήσεις `.env` στο root για να ορίσεις στοιχεία σύνδεσης:
```dotenv
DB_HOST=127.0.0.1
DB_USER=admin
DB_PASSWORD=password
DB_NAME=farmakeio_db
DB_PORT=3306
DB_POOL_SIZE=5
```

## Εκτέλεση
```bash
python3 main.py
```

## Βασική ροή χρήσης
1. Κάνε εγγραφή νέου χρήστη, συμπλήρωσε τα στοιχεία της φόρμας, επίλεξε ρόλο και σύνδεση.
2. Αν επιλέξεις ρόλο φαρμακείου, απαιτείται πρώτα υπογραφή συμβολαίου πριν από την κατάθεση παραγγελίας.

## Δομή φακέλων
- `main.py`: σημείο εκκίνησης της εφαρμογής.
- `app.py`: βασικό παράθυρο και routing οθονών.
- `screens/`: όλες οι οθόνες UI.
- `db.py`: σύνδεση MySQL και SQL σταθερές.
- `sql/`: schema + seed δεδομένων.
