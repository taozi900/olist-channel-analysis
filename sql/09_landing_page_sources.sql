-- 来源×匿名落地页的记录数；没有记录的组合不补成签约率。
SELECT COALESCE(NULLIF(TRIM(landing_page_id), ''), '(落地页未记录)') AS landing_page_id,
       origin_group AS channel,
       COUNT(*) AS lead_count
FROM lead_overview
GROUP BY COALESCE(NULLIF(TRIM(landing_page_id), ''), '(落地页未记录)'), origin_group
ORDER BY landing_page_id ASC, lead_count DESC, channel ASC;
