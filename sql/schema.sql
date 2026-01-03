-- DROP OLD DB
DROP DATABASE IF EXISTS farmakeio_db;

-- CREATE NEW DB
CREATE DATABASE farmakeio_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE farmakeio_db;

-- ======================
-- BASE TABLES
-- ======================

CREATE TABLE XRISTIS (
  username          VARCHAR(64) PRIMARY KEY,
  onomateponumo     VARCHAR(120),
  hashed_password   VARCHAR(255),
  tilefono          VARCHAR(30)
) ENGINE=InnoDB;

CREATE TABLE PROSOPIKO (
  username VARCHAR(64) PRIMARY KEY,
  CONSTRAINT fk_prosopiko_xristis
    FOREIGN KEY (username) REFERENCES XRISTIS(username)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE FARMAKEIO (
  username    VARCHAR(64),
  afm         VARCHAR(15),
  topothesia  VARCHAR(255),
  PRIMARY KEY (username, afm),
  UNIQUE KEY uq_farmakeio_username (username),
  UNIQUE KEY uq_farmakeio_afm (afm),
  CONSTRAINT fk_farmakeio_xristis
    FOREIGN KEY (username) REFERENCES XRISTIS(username)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE PROMITHEYTIS (
  supplier_id INT AUTO_INCREMENT PRIMARY KEY,
  onoma       VARCHAR(120),
  tilefono    VARCHAR(30)
) ENGINE=InnoDB;

CREATE TABLE DRASTIKI_OUSIA (
  onoma VARCHAR(120) PRIMARY KEY
) ENGINE=InnoDB;

CREATE TABLE PROION (
  product_id           INT AUTO_INCREMENT PRIMARY KEY,
  katigoria            VARCHAR(80),
  etairia              VARCHAR(120),
  periektikotita       FLOAT,
  onoma                VARCHAR(180),
  arx_kostos_temaxiou  DECIMAL(10,2)
) ENGINE=InnoDB;

CREATE TABLE PARAFARMAKO (
  product_id INT PRIMARY KEY,
  systatika  VARCHAR(255),
  CONSTRAINT fk_parafarmako_proion
    FOREIGN KEY (product_id) REFERENCES PROION(product_id)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE FARMAKO (
  product_id             INT PRIMARY KEY,
  elegxomeni_ousia       TINYINT(1),
  onoma_drastikis_ousias VARCHAR(120),
  CONSTRAINT fk_farmako_proion
    FOREIGN KEY (product_id) REFERENCES PROION(product_id)
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT fk_farmako_drastiki
    FOREIGN KEY (onoma_drastikis_ousias) REFERENCES DRASTIKI_OUSIA(onoma)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

-- ======================
-- WAREHOUSE / POSITIONS
-- ======================

CREATE TABLE APOTHIKI (
  storage_id  INT PRIMARY KEY,
  topothesia  VARCHAR(255)
) ENGINE=InnoDB;

CREATE TABLE THESI (
  ar_diadromou INT,
  ar_rafiou    INT,
  PRIMARY KEY (ar_diadromou, ar_rafiou)
) ENGINE=InnoDB;

CREATE TABLE THESI_BRISKETAI_APOTHIKI (
  storage_id    INT,
  ar_rafiou     INT,
  ar_diadromou  INT,
  PRIMARY KEY (storage_id, ar_diadromou, ar_rafiou),
  CONSTRAINT fk_tba_apothiki
    FOREIGN KEY (storage_id) REFERENCES APOTHIKI(storage_id)
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT fk_tba_thesi
    FOREIGN KEY (ar_diadromou, ar_rafiou) REFERENCES THESI(ar_diadromou, ar_rafiou)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE PROION_YPARXEI_APOTHIKI_THESI (
  product_id    INT,
  storage_id    INT,
  ar_diadromou  INT,
  ar_rafiou     INT,
  qty_in_stock  INT,
  PRIMARY KEY (product_id, storage_id, ar_diadromou, ar_rafiou),
  CONSTRAINT fk_pyat_proion
    FOREIGN KEY (product_id) REFERENCES PROION(product_id)
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT fk_pyat_thesi_apothiki
    FOREIGN KEY (storage_id, ar_diadromou, ar_rafiou)
    REFERENCES THESI_BRISKETAI_APOTHIKI(storage_id, ar_diadromou, ar_rafiou)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

-- ======================
-- BACKORDER
-- ======================

CREATE TABLE BACKORDER (
  storage_id       INT,
  backorder_id     INT AUTO_INCREMENT PRIMARY KEY,
  oloklirothike    TINYINT(1),
  hm_apostolis     DATE,
  CONSTRAINT fk_backorder_apothiki
    FOREIGN KEY (storage_id) REFERENCES APOTHIKI(storage_id)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

-- ======================
-- ORDERS / SHIPMENTS / AGREEMENTS
-- ======================

CREATE TABLE PARAGGELIA (
  order_id           INT AUTO_INCREMENT PRIMARY KEY,
  katastasi          ENUM('ΕΚΚΡΕΜΕΙ','ΣΕ ΕΠΕΞΕΡΓΑΣΙΑ','ΑΠΕΣΤΑΛΗ','ΑΚΥΡΩΘΗΚΕ'),
  arxiko_kostos      DECIMAL(10,2),
  ekptosi            DECIMAL(10,2),
  afm_farmakeiou     VARCHAR(15),
  hm_ora_ektelesis   DATETIME,
  KEY idx_paraggelia_afm (afm_farmakeiou),
  CONSTRAINT fk_paraggelia_farmakeio
    FOREIGN KEY (afm_farmakeiou) REFERENCES FARMAKEIO(afm)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE SYMBOLAIO (
  agreement_id        INT AUTO_INCREMENT PRIMARY KEY,
  suxnotita_paradosis ENUM('ΕΒΔΟΜΑΔΙΑΙΑ','ΔΕΚΑΠΕΝΘΗΜΕΡΗ','ΜΗΝΙΑΙΑ'),
  tropos_pliromis     ENUM('ΜΕΤΡΗΤΑ','ΚΑΡΤΑ','ΤΡΑΠΕΖΙΚΗ_ΜΕΤΑΦΟΡΑ'),
  afm_farmakeiou      VARCHAR(15),
  hm_ypografis        DATE,
  hm_liksis           DATE,
  diarkeia_mhnwn      INT,
  KEY idx_symbolaio_afm (afm_farmakeiou),
  CONSTRAINT fk_symbolaio_farmakeio
    FOREIGN KEY (afm_farmakeiou) REFERENCES FARMAKEIO(afm)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE APOSTOLI (
  shipment_id      INT AUTO_INCREMENT PRIMARY KEY,
  dromologio       INT,
  katastasi        ENUM('ΟΛΟΚΛΗΡΩΜΕΝΗ','ΜΕΡΙΚΗ'),
  hm_ora_apostolis DATETIME,
  teliko_kostos    DECIMAL(10,2),
  order_id         INT,
  KEY idx_apostoli_order (order_id),
  CONSTRAINT fk_apostoli_paraggelia
    FOREIGN KEY (order_id) REFERENCES PARAGGELIA(order_id)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

-- ======================
-- RELATION TABLES (COMPOSITE PKs)
-- ======================

CREATE TABLE PROMITHEYTIS_PROMITHEYEI_PROION (
  supplier_id  INT,
  product_id   INT,
  hm_enarksis  DATE,
  hm_liksis    DATE,
  PRIMARY KEY (supplier_id, product_id),
  CONSTRAINT fk_ppp_supplier
    FOREIGN KEY (supplier_id) REFERENCES PROMITHEYTIS(supplier_id)
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT fk_ppp_product
    FOREIGN KEY (product_id) REFERENCES PROION(product_id)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE PARAGGELEIA_PERIEXEI_PROION (
  order_id         INT,
  product_id       INT,
  temaxia_zitisis  INT,
  PRIMARY KEY (order_id, product_id),
  CONSTRAINT fk_pop_order
    FOREIGN KEY (order_id) REFERENCES PARAGGELIA(order_id)
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT fk_pop_product
    FOREIGN KEY (product_id) REFERENCES PROION(product_id)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE APOSTOLI_PERIEXEI_PROION (
  shipment_id        INT,
  product_id         INT,
  temaxia_apostolis  INT,
  PRIMARY KEY (shipment_id, product_id),
  CONSTRAINT fk_app_shipment
    FOREIGN KEY (shipment_id) REFERENCES APOSTOLI(shipment_id)
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT fk_app_product
    FOREIGN KEY (product_id) REFERENCES PROION(product_id)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE SYSTATIKA_PARAFARMAKOU (
  product_id INT,
  sustatiko  VARCHAR(120),
  PRIMARY KEY (product_id, sustatiko),
  CONSTRAINT fk_systatika_parafarmakou
    FOREIGN KEY (product_id) REFERENCES PARAFARMAKO(product_id)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE PROMITHEYTIS_APOSTELEI_PROION_BACKORDER (
  supplier_id   INT,
  product_id    INT,
  backorder_id  INT,
  quantity      INT,
  PRIMARY KEY (supplier_id, product_id, backorder_id),
  CONSTRAINT fk_papb_supplier
    FOREIGN KEY (supplier_id) REFERENCES PROMITHEYTIS(supplier_id)
  ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT fk_papb_product
    FOREIGN KEY (product_id) REFERENCES PROION(product_id)
  ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT fk_papb_backorder
    FOREIGN KEY (backorder_id) REFERENCES BACKORDER(backorder_id)
  ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

-- ======================
-- PERFORMANCE INDEXES
-- ======================

CREATE INDEX idx_pyat_storage ON PROION_YPARXEI_APOTHIKI_THESI (storage_id, ar_diadromou, ar_rafiou);
CREATE INDEX idx_pyat_product ON PROION_YPARXEI_APOTHIKI_THESI (product_id);
CREATE INDEX idx_pyat_product_qty ON PROION_YPARXEI_APOTHIKI_THESI (product_id, qty_in_stock);

CREATE INDEX idx_paraggelia_items_product ON PARAGGELEIA_PERIEXEI_PROION (product_id);
CREATE INDEX idx_paraggelia_status_date ON PARAGGELIA (katastasi, hm_ora_ektelesis);

CREATE INDEX idx_apostoli_items_product ON APOSTOLI_PERIEXEI_PROION (product_id);
CREATE INDEX idx_apostoli_order_date ON APOSTOLI (order_id, hm_ora_apostolis);

CREATE INDEX idx_symbolaio_liksis ON SYMBOLAIO (hm_liksis);

CREATE INDEX idx_promitheytis_products_product ON PROMITHEYTIS_PROMITHEYEI_PROION (product_id);

CREATE INDEX idx_backorder_storage ON BACKORDER (storage_id);
