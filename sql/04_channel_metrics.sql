-- 第四步：各来源在发布文件内的可见签约情况。
-- 口径：匹配到签约记录的MQL数 / 该来源全部MQL记录数。
-- 这是记录内可见签约占比，不是最终签约率，也不是渠道因果效果。
-- 保留空来源、unknown、未匹配签约及日期冲突记录。

SELECT
    origin_group AS channel,
    COUNT(*) AS lead_count,
    SUM(has_observed_won) AS observed_won_count,
    SUM(1 - has_observed_won) AS unmatched_won_count,
    100.0 * SUM(has_observed_won) / COUNT(*) AS observed_won_pct,
    SUM(date_order_issue) AS date_issue_count
FROM lead_overview
GROUP BY origin_group
ORDER BY lead_count DESC, channel ASC;
