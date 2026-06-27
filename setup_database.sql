-- =============================================================
-- Customer Support Agent — Supabase Database Setup
-- Run this SQL in your Supabase SQL editor
-- =============================================================

-- ---------------------------------------------------------------
-- CUSTOMERS
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customers (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    is_vip        BOOLEAN NOT NULL DEFAULT FALSE,
    fraud_score   FLOAT NOT NULL DEFAULT 0.0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------
-- ORDERS
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
    id                  TEXT PRIMARY KEY,
    customer_id         TEXT NOT NULL REFERENCES customers(id),
    status              TEXT NOT NULL,  -- pending | processing | shipped | delivered | cancelled
    items               JSONB NOT NULL DEFAULT '[]',
    total_amount        FLOAT NOT NULL,
    ordered_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    shipped_at          TIMESTAMPTZ,
    estimated_delivery  TIMESTAMPTZ,
    carrier             TEXT,
    tracking_number     TEXT
);

-- ---------------------------------------------------------------
-- RETURN REQUESTS
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS return_requests (
    id                  TEXT PRIMARY KEY,
    order_id            TEXT NOT NULL REFERENCES orders(id),
    customer_id         TEXT NOT NULL REFERENCES customers(id),
    reason              TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | completed
    requested_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at         TIMESTAMPTZ,
    return_window_days  INT NOT NULL DEFAULT 30
);

-- ---------------------------------------------------------------
-- RMA RECORDS
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rma_records (
    id                      TEXT PRIMARY KEY,
    return_request_id       TEXT NOT NULL REFERENCES return_requests(id),
    rma_number              TEXT NOT NULL UNIQUE,
    label_url               TEXT,
    warehouse_received_at   TIMESTAMPTZ,
    refund_amount           FLOAT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------
-- TICKETS
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tickets (
    id              TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES customers(id),
    order_id        TEXT,
    intent          TEXT,  -- wismo | return | refund | cancel | other | escalate
    status          TEXT NOT NULL DEFAULT 'open',  -- open | in_progress | escalated | resolved | closed
    priority        TEXT NOT NULL DEFAULT 'normal',  -- low | normal | high | urgent
    conversation    JSONB NOT NULL DEFAULT '[]',
    resolved_by     TEXT,  -- agent | human
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------
-- STORE CREDITS
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS store_credits (
    id          TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    amount      FLOAT NOT NULL,
    reason      TEXT NOT NULL,
    issued_by   TEXT NOT NULL DEFAULT 'agent',  -- agent | human
    status      TEXT NOT NULL DEFAULT 'active', -- active | used | expired
    issued_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ
);

-- ---------------------------------------------------------------
-- NOTIFICATIONS (sent emails / SMS — simulated in demo)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notifications (
    id          TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    ticket_id   TEXT REFERENCES tickets(id),
    channel     TEXT NOT NULL DEFAULT 'email', -- email | sms
    template    TEXT NOT NULL,                 -- rma_created | refund_processed | escalation | cancellation | store_credit | generic
    recipient   TEXT NOT NULL,
    body        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'sent',  -- sent | failed
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================
-- SEED DATA
-- =============================================================

-- ---------------------------------------------------------------
-- CUSTOMERS  (20 total)
-- ---------------------------------------------------------------
INSERT INTO customers (id, email, name, is_vip, fraud_score, created_at) VALUES
    -- Original 12
    ('CUST-001', 'alice@example.com',    'Alice Johnson',    TRUE,  0.0,  NOW() - INTERVAL '1 year'),
    ('CUST-002', 'bob@example.com',      'Bob Smith',        FALSE, 0.1,  NOW() - INTERVAL '8 months'),
    ('CUST-003', 'carol@example.com',    'Carol Williams',   FALSE, 0.0,  NOW() - INTERVAL '6 months'),
    ('CUST-004', 'dave@example.com',     'Dave Brown',       FALSE, 0.85, NOW() - INTERVAL '3 months'),
    ('CUST-005', 'eve@example.com',      'Eve Davis',        TRUE,  0.0,  NOW() - INTERVAL '2 years'),
    ('CUST-006', 'frank@example.com',    'Frank Miller',     FALSE, 0.2,  NOW() - INTERVAL '5 months'),
    ('CUST-007', 'grace@example.com',    'Grace Wilson',     FALSE, 0.0,  NOW() - INTERVAL '4 months'),
    ('CUST-008', 'henry@example.com',    'Henry Moore',      TRUE,  0.05, NOW() - INTERVAL '18 months'),
    ('CUST-009', 'irene@example.com',    'Irene Taylor',     FALSE, 0.6,  NOW() - INTERVAL '2 months'),
    ('CUST-010', 'jack@example.com',     'Jack Anderson',    FALSE, 0.0,  NOW() - INTERVAL '7 months'),
    ('CUST-011', 'karen@example.com',    'Karen Thomas',     FALSE, 0.0,  NOW() - INTERVAL '11 months'),
    ('CUST-012', 'liam@example.com',     'Liam Jackson',     TRUE,  0.0,  NOW() - INTERVAL '14 months'),
    -- New 8
    ('CUST-013', 'mia@example.com',      'Mia Roberts',      FALSE, 0.0,  NOW() - INTERVAL '3 weeks'),
    ('CUST-014', 'noah@example.com',     'Noah Harris',      FALSE, 0.45, NOW() - INTERVAL '9 months'),
    ('CUST-015', 'olivia@example.com',   'Olivia Clark',     TRUE,  0.0,  NOW() - INTERVAL '2 years'),
    ('CUST-016', 'peter@example.com',    'Peter Lewis',      FALSE, 0.0,  NOW() - INTERVAL '1 month'),
    ('CUST-017', 'quinn@example.com',    'Quinn Robinson',   FALSE, 0.75, NOW() - INTERVAL '5 weeks'),
    ('CUST-018', 'rachel@example.com',   'Rachel Walker',    TRUE,  0.0,  NOW() - INTERVAL '3 years'),
    ('CUST-019', 'sam@example.com',      'Sam Martinez',     FALSE, 0.0,  NOW() - INTERVAL '6 weeks'),
    ('CUST-020', 'tina@example.com',     'Tina Young',       FALSE, 0.0,  NOW() - INTERVAL '10 months')
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------
-- ORDERS  (30 total — original 13 + 17 new)
-- ---------------------------------------------------------------
INSERT INTO orders (id, customer_id, status, items, total_amount, ordered_at, shipped_at, estimated_delivery, carrier, tracking_number) VALUES
    -- Original 13
    ('ORD-1001', 'CUST-001', 'delivered',  '[{"sku":"SHOE-42","name":"Running Shoes","qty":1,"price":89.99}]',                                                                       89.99,   NOW()-INTERVAL '25 days', NOW()-INTERVAL '22 days', NOW()-INTERVAL '18 days', 'FedEx', 'FX123456789'),
    ('ORD-1002', 'CUST-002', 'shipped',    '[{"sku":"BAG-L","name":"Leather Bag","qty":1,"price":149.99}]',                                                                         149.99,  NOW()-INTERVAL '5 days',  NOW()-INTERVAL '3 days',  NOW()+INTERVAL '2 days',  'UPS',   'UPS987654321'),
    ('ORD-1003', 'CUST-003', 'processing', '[{"sku":"WATCH-01","name":"Smart Watch","qty":1,"price":299.99}]',                                                                      299.99,  NOW()-INTERVAL '2 days',  NULL,                     NOW()+INTERVAL '5 days',  NULL,    NULL),
    ('ORD-1004', 'CUST-004', 'delivered',  '[{"sku":"LAPTOP-PRO","name":"Laptop Pro","qty":1,"price":1299.99}]',                                                                    1299.99, NOW()-INTERVAL '40 days', NOW()-INTERVAL '37 days', NOW()-INTERVAL '33 days', 'FedEx', 'FX999111222'),
    ('ORD-1005', 'CUST-005', 'shipped',    '[{"sku":"PHONE-X","name":"Phone X","qty":1,"price":799.99}]',                                                                           799.99,  NOW()-INTERVAL '10 days', NOW()-INTERVAL '7 days',  NOW()-INTERVAL '1 day',   'USPS',  'USPS112233445'),
    ('ORD-1006', 'CUST-006', 'delivered',  '[{"sku":"HDPHONE-BT","name":"Bluetooth Headphones","qty":1,"price":59.99}]',                                                            59.99,   NOW()-INTERVAL '15 days', NOW()-INTERVAL '12 days', NOW()-INTERVAL '9 days',  'DHL',   'DHL556677889'),
    ('ORD-1007', 'CUST-007', 'pending',    '[{"sku":"DESK-LAMP","name":"LED Desk Lamp","qty":2,"price":29.99}]',                                                                    59.98,   NOW()-INTERVAL '1 day',   NULL,                     NOW()+INTERVAL '7 days',  NULL,    NULL),
    ('ORD-1008', 'CUST-008', 'delivered',  '[{"sku":"CAMERA-4K","name":"4K Camera","qty":1,"price":549.99}]',                                                                       549.99,  NOW()-INTERVAL '20 days', NOW()-INTERVAL '17 days', NOW()-INTERVAL '13 days', 'FedEx', 'FX444555666'),
    ('ORD-1009', 'CUST-009', 'cancelled',  '[{"sku":"JACKET-L","name":"Winter Jacket","qty":1,"price":179.99}]',                                                                    179.99,  NOW()-INTERVAL '8 days',  NULL,                     NULL,                     NULL,    NULL),
    ('ORD-1010', 'CUST-010', 'delivered',  '[{"sku":"TABLET-10","name":"Tablet 10 inch","qty":1,"price":349.99}]',                                                                  349.99,  NOW()-INTERVAL '12 days', NOW()-INTERVAL '9 days',  NOW()-INTERVAL '5 days',  'UPS',   'UPS223344556'),
    ('ORD-1011', 'CUST-011', 'shipped',    '[{"sku":"KEYBOARD-M","name":"Mechanical Keyboard","qty":1,"price":129.99}]',                                                            129.99,  NOW()-INTERVAL '4 days',  NOW()-INTERVAL '2 days',  NOW()+INTERVAL '3 days',  'DHL',   'DHL778899001'),
    ('ORD-1042', 'CUST-001', 'shipped',    '[{"sku":"SNEAKER-10","name":"Classic Sneakers","qty":1,"price":75.00},{"sku":"SOCK-3PK","name":"Socks 3-Pack","qty":1,"price":12.99}]', 87.99,   NOW()-INTERVAL '6 days',  NOW()-INTERVAL '4 days',  NOW()+INTERVAL '1 day',   'USPS',  'USPS998877665'),
    ('ORD-0998', 'CUST-003', 'delivered',  '[{"sku":"MONITOR-27","name":"27 inch Monitor","qty":1,"price":399.99}]',                                                                399.99,  NOW()-INTERVAL '35 days', NOW()-INTERVAL '32 days', NOW()-INTERVAL '28 days', 'FedEx', 'FX777888999'),
    -- Alice (CUST-001) order history — delivered older orders
    ('ORD-1050', 'CUST-001', 'delivered',  '[{"sku":"YOGA-MAT","name":"Yoga Mat","qty":1,"price":45.00}]',                                                                          45.00,   NOW()-INTERVAL '60 days', NOW()-INTERVAL '57 days', NOW()-INTERVAL '53 days', 'USPS',  'USPS556677881'),
    ('ORD-1051', 'CUST-001', 'delivered',  '[{"sku":"WATER-BTL","name":"Insulated Water Bottle","qty":2,"price":24.99}]',                                                           49.98,   NOW()-INTERVAL '90 days', NOW()-INTERVAL '87 days', NOW()-INTERVAL '84 days', 'UPS',   'UPS334455667'),
    -- Liam (CUST-012) — VIP with active order
    ('ORD-1052', 'CUST-012', 'shipped',    '[{"sku":"SUIT-BLK","name":"Business Suit","qty":1,"price":699.99}]',                                                                    699.99,  NOW()-INTERVAL '7 days',  NOW()-INTERVAL '5 days',  NOW()+INTERVAL '2 days',  'FedEx', 'FX112233001'),
    -- Mia (CUST-013) — brand new customer, first order just placed
    ('ORD-1053', 'CUST-013', 'pending',    '[{"sku":"SKINCARE-KT","name":"Skincare Kit","qty":1,"price":89.00}]',                                                                   89.00,   NOW()-INTERVAL '2 hours', NULL,                     NOW()+INTERVAL '6 days',  NULL,    NULL),
    -- Noah (CUST-014) — elevated fraud, multi-item order
    ('ORD-1054', 'CUST-014', 'delivered',  '[{"sku":"PHONE-Y","name":"Phone Y","qty":1,"price":899.99},{"sku":"CASE-Y","name":"Phone Case","qty":2,"price":19.99}]',                939.97,  NOW()-INTERVAL '18 days', NOW()-INTERVAL '15 days', NOW()-INTERVAL '11 days', 'UPS',   'UPS667788992'),
    -- Olivia (CUST-015) — VIP, high-value delivered
    ('ORD-1055', 'CUST-015', 'delivered',  '[{"sku":"DIAMOND-W","name":"Diamond Watch","qty":1,"price":2499.99}]',                                                                  2499.99, NOW()-INTERVAL '30 days', NOW()-INTERVAL '27 days', NOW()-INTERVAL '23 days', 'FedEx', 'FX990011223'),
    -- Peter (CUST-016) — new customer, processing
    ('ORD-1056', 'CUST-016', 'processing', '[{"sku":"DESK-CHAIR","name":"Ergonomic Desk Chair","qty":1,"price":349.00}]',                                                           349.00,  NOW()-INTERVAL '1 day',   NULL,                     NOW()+INTERVAL '8 days',  NULL,    NULL),
    -- Quinn (CUST-017) — high fraud, delivered
    ('ORD-1057', 'CUST-017', 'delivered',  '[{"sku":"GAMING-PC","name":"Gaming PC","qty":1,"price":1899.99}]',                                                                      1899.99, NOW()-INTERVAL '22 days', NOW()-INTERVAL '19 days', NOW()-INTERVAL '15 days', 'FedEx', 'FX223344005'),
    -- Rachel (CUST-018) — VIP, multiple items, shipped
    ('ORD-1058', 'CUST-018', 'shipped',    '[{"sku":"HANDBAG-LV","name":"Designer Handbag","qty":1,"price":1199.00},{"sku":"WALLET-LV","name":"Designer Wallet","qty":1,"price":399.00}]', 1598.00, NOW()-INTERVAL '9 days', NOW()-INTERVAL '6 days', NOW()+INTERVAL '1 day', 'UPS', 'UPS881122334'),
    -- Sam (CUST-019) — regular customer, cancelled then re-ordered
    ('ORD-1059', 'CUST-019', 'cancelled',  '[{"sku":"BLENDER-X","name":"High-Speed Blender","qty":1,"price":129.99}]',                                                              129.99,  NOW()-INTERVAL '14 days', NULL,                     NULL,                     NULL,    NULL),
    ('ORD-1060', 'CUST-019', 'shipped',    '[{"sku":"BLENDER-X","name":"High-Speed Blender","qty":1,"price":129.99}]',                                                              129.99,  NOW()-INTERVAL '5 days',  NOW()-INTERVAL '3 days',  NOW()+INTERVAL '2 days',  'DHL',   'DHL990011225'),
    -- Tina (CUST-020) — delivered with pending return window
    ('ORD-1061', 'CUST-020', 'delivered',  '[{"sku":"AIR-PURIF","name":"Air Purifier","qty":1,"price":249.99}]',                                                                    249.99,  NOW()-INTERVAL '10 days', NOW()-INTERVAL '7 days',  NOW()-INTERVAL '4 days',  'UPS',   'UPS556677003'),
    -- Bob (CUST-002) — older resolved order
    ('ORD-1062', 'CUST-002', 'delivered',  '[{"sku":"SNEAKER-RS","name":"Road Runner Sneakers","qty":1,"price":109.99}]',                                                           109.99,  NOW()-INTERVAL '45 days', NOW()-INTERVAL '42 days', NOW()-INTERVAL '38 days', 'USPS',  'USPS112244556'),
    -- Karen (CUST-011) — older delivered order
    ('ORD-1063', 'CUST-011', 'delivered',  '[{"sku":"COFFEE-MK","name":"Espresso Machine","qty":1,"price":299.00}]',                                                                299.00,  NOW()-INTERVAL '50 days', NOW()-INTERVAL '47 days', NOW()-INTERVAL '43 days', 'FedEx', 'FX334455117'),
    -- Grace (CUST-007) — new order after pending
    ('ORD-1064', 'CUST-007', 'processing', '[{"sku":"DESK-LAMP","name":"LED Desk Lamp","qty":1,"price":29.99},{"sku":"USB-HUB","name":"USB-C Hub","qty":1,"price":39.99}]',         69.98,   NOW()-INTERVAL '3 days',  NULL,                     NOW()+INTERVAL '4 days',  NULL,    NULL),
    -- Henry (CUST-008) — old order (order history test)
    ('ORD-1065', 'CUST-008', 'delivered',  '[{"sku":"DRONE-M","name":"Mini Drone","qty":1,"price":199.99}]',                                                                        199.99,  NOW()-INTERVAL '55 days', NOW()-INTERVAL '52 days', NOW()-INTERVAL '48 days', 'UPS',   'UPS667799110'),
    -- Eve (CUST-005) — older delivered order
    ('ORD-1066', 'CUST-005', 'delivered',  '[{"sku":"EARBUDS-W","name":"Wireless Earbuds","qty":1,"price":149.00}]',                                                                149.00,  NOW()-INTERVAL '42 days', NOW()-INTERVAL '39 days', NOW()-INTERVAL '35 days', 'DHL',   'DHL334411228')
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------
-- RETURN REQUESTS  (12 total — original 5 + 7 new)
-- ---------------------------------------------------------------
INSERT INTO return_requests (id, order_id, customer_id, reason, status, requested_at, approved_at, return_window_days) VALUES
    -- Original 5
    ('RET-001', 'ORD-1001', 'CUST-001', 'Item does not fit',                'approved',  NOW()-INTERVAL '3 days',  NOW()-INTERVAL '2 days',  30),
    ('RET-002', 'ORD-1006', 'CUST-006', 'Defective product',                'pending',   NOW()-INTERVAL '1 day',   NULL,                     30),
    ('RET-003', 'ORD-1010', 'CUST-010', 'Changed mind',                     'rejected',  NOW()-INTERVAL '6 days',  NULL,                     30),
    ('RET-004', 'ORD-1008', 'CUST-008', 'Not as described',                 'approved',  NOW()-INTERVAL '10 days', NOW()-INTERVAL '9 days',  30),
    ('RET-005', 'ORD-0998', 'CUST-003', 'Arrived damaged',                  'completed', NOW()-INTERVAL '25 days', NOW()-INTERVAL '24 days', 30),
    -- New 7
    ('RET-006', 'ORD-1054', 'CUST-014', 'Wrong item received',              'pending',   NOW()-INTERVAL '2 days',  NULL,                     30),
    ('RET-007', 'ORD-1055', 'CUST-015', 'Item not as described',            'approved',  NOW()-INTERVAL '5 days',  NOW()-INTERVAL '4 days',  30),
    ('RET-008', 'ORD-1061', 'CUST-020', 'Defective — stopped working',      'pending',   NOW()-INTERVAL '1 day',   NULL,                     30),
    ('RET-009', 'ORD-1057', 'CUST-017', 'Changed mind',                     'rejected',  NOW()-INTERVAL '4 days',  NULL,                     30),
    ('RET-010', 'ORD-1062', 'CUST-002', 'Sizing issue',                     'completed', NOW()-INTERVAL '30 days', NOW()-INTERVAL '29 days', 30),
    ('RET-011', 'ORD-1063', 'CUST-011', 'Machine stopped working',          'approved',  NOW()-INTERVAL '8 days',  NOW()-INTERVAL '7 days',  30),
    ('RET-012', 'ORD-1050', 'CUST-001', 'Poor quality',                     'completed', NOW()-INTERVAL '40 days', NOW()-INTERVAL '39 days', 30)
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------
-- RMA RECORDS  (9 total — original 3 + 6 new)
-- ---------------------------------------------------------------
INSERT INTO rma_records (id, return_request_id, rma_number, label_url, warehouse_received_at, refund_amount, created_at) VALUES
    -- Original 3
    ('RMA-001', 'RET-001', 'RMA-20240101-001', 'https://labels.example.com/rma-001.pdf', NULL,                     89.99,   NOW()-INTERVAL '2 days'),
    ('RMA-002', 'RET-004', 'RMA-20240102-002', 'https://labels.example.com/rma-002.pdf', NOW()-INTERVAL '5 days',  549.99,  NOW()-INTERVAL '9 days'),
    ('RMA-003', 'RET-005', 'RMA-20240103-003', 'https://labels.example.com/rma-003.pdf', NOW()-INTERVAL '20 days', 399.99,  NOW()-INTERVAL '24 days'),
    -- New 6
    ('RMA-004', 'RET-007', 'RMA-20240107-004', 'https://labels.example.com/rma-007.pdf', NOW()-INTERVAL '2 days',  2499.99, NOW()-INTERVAL '4 days'),
    ('RMA-005', 'RET-010', 'RMA-20240110-005', 'https://labels.example.com/rma-010.pdf', NOW()-INTERVAL '25 days', 109.99,  NOW()-INTERVAL '29 days'),
    ('RMA-006', 'RET-011', 'RMA-20240111-006', 'https://labels.example.com/rma-011.pdf', NOW()-INTERVAL '4 days',  299.00,  NOW()-INTERVAL '7 days'),
    ('RMA-007', 'RET-012', 'RMA-20240112-007', 'https://labels.example.com/rma-012.pdf', NOW()-INTERVAL '36 days', 45.00,   NOW()-INTERVAL '39 days'),
    ('RMA-008', 'RET-006', 'RMA-20240106-008', 'https://labels.example.com/rma-006.pdf', NULL,                     NULL,    NOW()-INTERVAL '2 days'),
    ('RMA-009', 'RET-008', 'RMA-20240108-009', 'https://labels.example.com/rma-008.pdf', NULL,                     NULL,    NOW()-INTERVAL '1 day')
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------
-- TICKETS  (15 total — original 5 + 10 new)
-- ---------------------------------------------------------------
INSERT INTO tickets (id, customer_id, order_id, intent, status, priority, conversation, resolved_by, created_at, updated_at) VALUES
    -- Original 5
    ('TKT-001', 'CUST-001', 'ORD-1001', 'return',  'resolved',   'normal', '[{"role":"user","content":"I want to return my shoes"},{"role":"agent","content":"Return approved, RMA sent."}]',                                     'agent', NOW()-INTERVAL '3 days',  NOW()-INTERVAL '2 days'),
    ('TKT-002', 'CUST-002', 'ORD-1002', 'wismo',   'open',       'normal', '[{"role":"user","content":"Where is my order?"}]',                                                                                                    NULL,    NOW()-INTERVAL '1 day',   NOW()-INTERVAL '1 day'),
    ('TKT-003', 'CUST-004', 'ORD-1004', 'escalate','escalated',  'urgent', '[{"role":"user","content":"I need a manager now"}]',                                                                                                   NULL,    NOW()-INTERVAL '2 days',  NOW()-INTERVAL '2 days'),
    ('TKT-004', 'CUST-008', 'ORD-1008', 'refund',  'resolved',   'high',   '[{"role":"user","content":"Where is my refund?"},{"role":"agent","content":"Refund of $549.99 initiated."}]',                                         'agent', NOW()-INTERVAL '8 days',  NOW()-INTERVAL '7 days'),
    ('TKT-005', 'CUST-003', 'ORD-0998', 'refund',  'resolved',   'normal', '[{"role":"user","content":"Refund for monitor?"},{"role":"agent","content":"Refund processed."}]',                                                    'agent', NOW()-INTERVAL '20 days', NOW()-INTERVAL '19 days'),
    -- New 10
    ('TKT-006', 'CUST-014', 'ORD-1054', 'return',  'in_progress','high',   '[{"role":"user","content":"I received the wrong item, I want to return it."},{"role":"agent","content":"I have created an RMA for you. RMA-008."}]',  NULL,    NOW()-INTERVAL '2 days',  NOW()-INTERVAL '1 day'),
    ('TKT-007', 'CUST-015', 'ORD-1055', 'refund',  'escalated',  'urgent', '[{"role":"user","content":"My watch is not what was advertised. I want a full refund immediately."},{"role":"agent","content":"Escalating to a specialist."}]', NULL, NOW()-INTERVAL '5 days', NOW()-INTERVAL '4 days'),
    ('TKT-008', 'CUST-017', 'ORD-1057', 'return',  'resolved',   'normal', '[{"role":"user","content":"I want to return my gaming PC."},{"role":"agent","content":"Return window has passed. Unable to process."}]',             'agent', NOW()-INTERVAL '4 days',  NOW()-INTERVAL '3 days'),
    ('TKT-009', 'CUST-019', 'ORD-1059', 'wismo',   'resolved',   'normal', '[{"role":"user","content":"Where is my blender?"},{"role":"agent","content":"That order was cancelled. A new order ORD-1060 has shipped."}]',        'agent', NOW()-INTERVAL '5 days',  NOW()-INTERVAL '4 days'),
    ('TKT-010', 'CUST-020', 'ORD-1061', 'return',  'in_progress','normal', '[{"role":"user","content":"My air purifier stopped working after 3 days."},{"role":"agent","content":"I have raised a return request RET-008."}]',   NULL,    NOW()-INTERVAL '1 day',   NOW()-INTERVAL '12 hours'),
    ('TKT-011', 'CUST-012', 'ORD-1052', 'wismo',   'open',       'high',   '[{"role":"user","content":"When will my suit arrive?"}]',                                                                                             NULL,    NOW()-INTERVAL '3 hours', NOW()-INTERVAL '3 hours'),
    ('TKT-012', 'CUST-011', 'ORD-1063', 'refund',  'in_progress','normal', '[{"role":"user","content":"My espresso machine broke, I want a refund."},{"role":"agent","content":"Return approved, awaiting refund processing."}]', NULL,    NOW()-INTERVAL '8 days',  NOW()-INTERVAL '7 days'),
    ('TKT-013', 'CUST-016', 'ORD-1056', 'wismo',   'open',       'normal', '[{"role":"user","content":"Has my chair shipped yet?"}]',                                                                                             NULL,    NOW()-INTERVAL '1 day',   NOW()-INTERVAL '1 day'),
    ('TKT-014', 'CUST-009', 'ORD-1009', 'other',   'resolved',   'normal', '[{"role":"user","content":"Why was my order cancelled?"},{"role":"agent","content":"The item went out of stock. A refund was automatically issued."}]','agent', NOW()-INTERVAL '7 days',  NOW()-INTERVAL '6 days'),
    ('TKT-015', 'CUST-018', 'ORD-1058', 'wismo',   'open',       'urgent', '[{"role":"user","content":"My designer bag has not arrived yet and it was supposed to be here yesterday."}]',                                         NULL,    NOW()-INTERVAL '4 hours', NOW()-INTERVAL '4 hours')
ON CONFLICT (id) DO NOTHING;
