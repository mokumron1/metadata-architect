CREATE TABLE finance.global_revenue_agg_v1 (
    id          BIGSERIAL PRIMARY KEY,
    report_date DATE        NOT NULL,
    region_code VARCHAR(8)  NOT NULL,
    currency    CHAR(3)     NOT NULL,
    revenue     NUMERIC(18, 4) NOT NULL DEFAULT 0,
    cost        NUMERIC(18, 4),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
