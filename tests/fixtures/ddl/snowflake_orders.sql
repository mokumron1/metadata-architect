CREATE TABLE sales.orders (
    order_id      NUMBER(38, 0)   NOT NULL PRIMARY KEY,
    customer_id   NUMBER(38, 0)   NOT NULL,
    order_date    DATE            NOT NULL,
    status        VARCHAR(32)     NOT NULL DEFAULT 'PENDING',
    total_amount  FLOAT           NOT NULL,
    currency_code CHAR(3)         NOT NULL,
    region        VARCHAR(64),
    FOREIGN KEY (customer_id) REFERENCES sales.customers(customer_id)
);
