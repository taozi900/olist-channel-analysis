-- 按首次联系月份与来源同时分组，便于后续查看月份构成差异。
-- 此表只包含有线索的组合；没有线索的组合不补成0%签约占比。
-- 签约记录可以晚于首次联系月份；这里不是统计每月发生的签约数。

SELECT
    first_contact_month AS contact_month,
    origin_group AS channel,
    COUNT(*) AS lead_count,
    SUM(has_observed_won) AS observed_won_count,
    SUM(1 - has_observed_won) AS unmatched_won_count,
    100.0 * SUM(has_observed_won) / COUNT(*) AS observed_won_pct,
    SUM(date_order_issue) AS date_issue_count
FROM lead_overview
GROUP BY first_contact_month, origin_group
ORDER BY contact_month ASC, lead_count DESC, channel ASC;
