-- 按匿名落地页定位unknown与空白来源；两类分别计数。
-- 按unknown数量排序，优先级不依据签约结果或小样本高比例。
WITH page_counts AS (
    SELECT COALESCE(NULLIF(TRIM(landing_page_id), ''), '(落地页未记录)') AS landing_page_id,
           COUNT(*) AS lead_count,
           SUM(CASE WHEN origin_group = 'unknown' THEN 1 ELSE 0 END) AS unknown_count,
           SUM(CASE WHEN origin_group = '(未记录)' THEN 1 ELSE 0 END) AS blank_count
    FROM lead_overview
    GROUP BY COALESCE(NULLIF(TRIM(landing_page_id), ''), '(落地页未记录)')
)
SELECT landing_page_id, lead_count, unknown_count, blank_count,
       lead_count - unknown_count - blank_count AS other_label_count,
       100.0 * unknown_count / lead_count AS unknown_pct,
       100.0 * blank_count / lead_count AS blank_pct,
       100.0 * (unknown_count + blank_count) / lead_count AS unclear_pct
FROM page_counts
ORDER BY unknown_count DESC, landing_page_id ASC;
