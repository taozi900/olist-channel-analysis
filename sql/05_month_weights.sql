-- 月份权重及各来源的月内占比；保留未舍入数参与加权。
-- 同一个月份的month_weight，对三来源完全相同。
-- weighted_contribution_pp是该月对最终标准化占比的贡献，单位为百分点。

WITH selected_channels(channel) AS (
    VALUES ('organic_search'), ('paid_search'), ('social')
),
monthly AS (
    SELECT first_contact_month AS contact_month,
           origin_group AS channel,
           COUNT(*) AS lead_count,
           SUM(has_observed_won) AS won_count,
           SUM(date_order_issue) AS date_issue_count
    FROM lead_overview
    WHERE origin_group IN (SELECT channel FROM selected_channels)
    GROUP BY first_contact_month, origin_group
),
common_months AS (
    SELECT contact_month
    FROM monthly
    GROUP BY contact_month
    HAVING COUNT(*) = (SELECT COUNT(*) FROM selected_channels)
),
pooled_months AS (
    SELECT m.contact_month, SUM(m.lead_count) AS pooled_lead_count
    FROM monthly AS m
    JOIN common_months AS c ON m.contact_month = c.contact_month
    GROUP BY m.contact_month
),
weights AS (
    SELECT contact_month,
           pooled_lead_count,
           1.0 * pooled_lead_count / SUM(pooled_lead_count) OVER () AS month_weight
    FROM pooled_months
)
SELECT m.contact_month,
       m.channel,
       m.lead_count,
       m.won_count AS observed_won_count,
       100.0 * m.won_count / m.lead_count AS observed_won_pct,
       w.pooled_lead_count,
       w.month_weight,
       w.month_weight * 100.0 * m.won_count / m.lead_count AS weighted_contribution_pp,
       m.date_issue_count
FROM monthly AS m
JOIN weights AS w ON m.contact_month = w.contact_month
ORDER BY m.contact_month, m.channel;
