CREATE TABLE public.order_lines (
    line_id     SERIAL PRIMARY KEY,
    order_id    INTEGER NOT NULL,
    product_id  INTEGER NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 1,
    unit_price  NUMERIC(10, 2) NOT NULL,
    discount    NUMERIC(5, 4) DEFAULT 0,
    FOREIGN KEY (order_id) REFERENCES public.orders(id),
    FOREIGN KEY (product_id) REFERENCES public.products(id)
);
