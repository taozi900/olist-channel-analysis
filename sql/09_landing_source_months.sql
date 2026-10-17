-- 按首次联系月份×匿名落地页分组；区分数量与页内比例。
WITH monthly AS (
    SELECT first_contact_month AS contact_month,
           COALESCE(NULLIF(TRIM(landing_page_id), ''), '(落地页未记录)') AS landing_page_id,
           COUNT(*) AS lead_count,
           SUM(CASE WHEN origin_group = 'unknown' THEN 1 ELSE 0 END) AS unknown_count,
           SUM(CASE WHEN origin_group = '(未记录)' THEN 1 ELSE 0 END) AS blank_count
    FROM lead_overview
    GROUP BY first_contact_month, COALESCE(NULLIF(TRIM(landing_page_id), ''), '(落地页未记录)')
)
SELECT contact_month, landing_page_id, lead_count, unknown_count, blank_count,
       lead_count - unknown_count - blank_count AS other_label_count,
       100.0 * unknown_count / lead_count AS unknown_pct,
       100.0 * blank_count / lead_count AS blank_pct,
       100.0 * (unknown_count + blank_count) / lead_count AS unclear_pct
FROM monthly
ORDER BY contact_month ASC, landing_page_id ASC;
