-- 日期范围只表示文件内记录覆盖，不代表已知完整随访截止。
-- 所有可见签约均纳入覆盖检查，包括日期冲突记录。

SELECT
    COUNT(*) AS lead_count,
    SUM(has_observed_won) AS observed_won_count,
    SUM(1 - has_observed_won) AS unmatched_won_count,
    MIN(first_contact_date) AS first_contact_min,
    MAX(first_contact_date) AS first_contact_max,
    MIN(won_date) AS won_min,
    MAX(won_date) AS won_max,
    SUM(date_order_issue) AS date_issue_count,
    SUM(CASE
        WHEN DATE(won_date) > (SELECT MAX(first_contact_date) FROM mql)
        THEN 1 ELSE 0
    END) AS won_after_last_contact_date_count
FROM lead_overview;
