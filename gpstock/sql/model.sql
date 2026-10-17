-- Star schema for Power BI, built from the app's exported tables.
-- $START / $END are replaced with the reporting period.

-- ---------- dimensions ----------
CREATE OR REPLACE TABLE dim_date AS
SELECT d::DATE AS date, date_trunc('month', d)::DATE AS month, strftime(d, '%b %Y') AS month_label,
       isodow(d) AS weekday_no, strftime(d, '%a') AS weekday, isodow(d) <> 7 AS is_open_day,
       CASE WHEN month(d) IN (10, 11, 12, 1, 2) THEN 'Winter (flu season)' ELSE 'Rest of year' END AS season
FROM generate_series($START, $END, INTERVAL 1 DAY) AS g(d);

CREATE OR REPLACE TABLE dim_site AS SELECT site_id, name AS site FROM src_sites;

CREATE OR REPLACE TABLE dim_item AS
SELECT i.item_id, i.name AS item, c.name AS category, i.unit, i.supplier, i.tracked AS tracks_expiry,
       c.name IN ('Medical Consumables', 'Medical Equipment', 'PPE') AS is_clinical
FROM src_items i JOIN src_categories c USING (category_id);

CREATE OR REPLACE TABLE dim_staff AS SELECT user_id, job_title, role FROM src_users;

-- ---------- facts ----------
-- What each item really cost us over the year, used to value stock that goes out.
CREATE OR REPLACE TABLE item_avg_cost AS
SELECT item_id, sum(quantity * unit_cost) / sum(quantity) AS avg_unit_cost
FROM src_movements WHERE type = 'in' AND unit_cost IS NOT NULL GROUP BY item_id;

CREATE OR REPLACE TABLE fact_movement AS
SELECT m.movement_id, m.date::TIMESTAMP AS moved_at, m.date::DATE AS date, m.item_id, m.site_id, m.user_id,
       m.type, m.quantity,
       CASE WHEN m.type = 'in' THEN m.quantity ELSE -m.quantity END AS signed_quantity,
       CASE WHEN m.type = 'out' THEN m.reason
            WHEN m.source = 'Opening stock' THEN 'opening'
            WHEN m.source LIKE 'Transfer%' THEN 'transfer in'
            ELSE 'purchase' END AS movement_kind,
       m.source, m.batch_id, m.request_id,
       round(m.quantity * coalesce(m.unit_cost, c.avg_unit_cost), 2) AS value_gbp,
       CASE WHEN m.type = 'in' AND m.source NOT IN ('Opening stock') AND m.source NOT LIKE 'Transfer%'
            THEN round(m.quantity * m.unit_cost, 2) ELSE 0 END AS spend_gbp,
       CASE WHEN m.reason IN ('expired', 'damaged', 'lost') THEN round(m.quantity * c.avg_unit_cost, 2) ELSE 0 END AS waste_gbp
FROM src_movements m LEFT JOIN item_avg_cost c USING (item_id);

-- Closing stock for every item, at every site, on every day: the running total of its movements.
CREATE OR REPLACE TABLE fact_daily_stock AS
WITH spine AS (
    SELECT d.date, s.site_id, i.item_id
    FROM dim_date d CROSS JOIN dim_site s CROSS JOIN dim_item i
), daily AS (
    SELECT date, site_id, item_id, sum(signed_quantity) AS net,
           sum(quantity) FILTER (WHERE movement_kind = 'used') AS used
    FROM fact_movement GROUP BY ALL
)
SELECT sp.date, sp.site_id, sp.item_id,
       coalesce(d.used, 0) AS used,
       sum(coalesce(d.net, 0)) OVER (PARTITION BY sp.site_id, sp.item_id ORDER BY sp.date) AS closing_stock,
       ss.min_quantity AS reorder_level
FROM spine sp
LEFT JOIN daily d USING (date, site_id, item_id)
LEFT JOIN src_site_stock ss ON ss.site_id = sp.site_id AND ss.item_id = sp.item_id;

ALTER TABLE fact_daily_stock ADD COLUMN out_of_stock BOOLEAN;
ALTER TABLE fact_daily_stock ADD COLUMN below_reorder BOOLEAN;
UPDATE fact_daily_stock SET out_of_stock = closing_stock <= 0, below_reorder = closing_stock <= reorder_level;

CREATE OR REPLACE TABLE fact_request AS
SELECT request_id, requested_at::TIMESTAMP::DATE AS date, item_id, site_id, quantity, priority, status,
       requested_by, reviewed_by,
       round(date_diff('minute', requested_at::TIMESTAMP, reviewed_at::TIMESTAMP) / 60.0, 1) AS hours_to_review,
       round(date_diff('minute', requested_at::TIMESTAMP, fulfilled_at::TIMESTAMP) / 1440.0, 1) AS days_to_fulfil
FROM src_requests;

CREATE OR REPLACE TABLE fact_batch AS
SELECT b.batch_id, b.item_id, b.site_id, b.batch_number, b.received_at::DATE AS received_at,
       b.expiry_date::DATE AS expiry_date, b.received_quantity, b.quantity_now,
       round(b.quantity_now * c.avg_unit_cost, 2) AS value_now_gbp,
       date_diff('day', $END, b.expiry_date::DATE) AS days_to_expiry,
       CASE WHEN b.expiry_date IS NULL THEN 'No expiry'
            WHEN b.quantity_now = 0 THEN 'Used up'
            WHEN b.expiry_date::DATE < $END THEN 'Expired'
            WHEN b.expiry_date::DATE <= $END + INTERVAL 60 DAY THEN 'Expiring within 60 days'
            ELSE 'OK' END AS expiry_status
FROM src_batches b LEFT JOIN item_avg_cost c USING (item_id);

-- ---------- marts ----------
CREATE OR REPLACE TABLE mart_item_performance AS
WITH stock AS (
    SELECT f.site_id, f.item_id, sum(f.used) AS used_units,
           round(sum(f.used) / count(*) FILTER (WHERE d.is_open_day), 3) AS avg_daily_use,
           count(*) FILTER (WHERE f.out_of_stock AND d.is_open_day) AS days_out_of_stock,
           count(*) FILTER (WHERE f.below_reorder) AS days_below_reorder,
           arg_max(f.closing_stock, f.date) AS stock_now
    FROM fact_daily_stock f JOIN dim_date d USING (date) GROUP BY ALL
), money AS (
    SELECT site_id, item_id, sum(spend_gbp) AS spend_gbp, sum(waste_gbp) AS waste_gbp,
           count(*) FILTER (WHERE movement_kind = 'purchase') AS deliveries
    FROM fact_movement GROUP BY ALL
)
SELECT s.*, m.spend_gbp, m.waste_gbp, m.deliveries,
       round(s.stock_now / nullif(s.avg_daily_use, 0), 1) AS days_of_cover
FROM stock s JOIN money m USING (site_id, item_id);
