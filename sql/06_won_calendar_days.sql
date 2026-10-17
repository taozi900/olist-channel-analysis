-- 仅获取文件内匹配到签约的线索，不给未签约者补0天。
-- DATE去掉时分秒；差值是日历天数，不是精确24小时耗时。
-- 原记录全部保留，负值或无法解析日期的记录单独标记。

SELECT
    mql_id,
    origin_group AS channel,
    first_contact_date,
    won_date,
    CAST(JULIANDAY(DATE(won_date)) - JULIANDAY(DATE(first_contact_date)) AS INTEGER) AS calendar_days_to_won,
    CASE
        WHEN DATE(won_date) IS NULL OR DATE(first_contact_date) IS NULL THEN 'invalid_date'
        WHEN DATE(won_date) < DATE(first_contact_date) THEN 'negative_interval'
        ELSE 'valid_duration'
    END AS duration_status
FROM lead_overview
WHERE has_observed_won = 1
ORDER BY mql_id;
