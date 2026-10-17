-- 第五步：三来源使用相同的首次联系月份权重。
-- 本次方案固定比较自然搜索、付费搜索、社交。
-- 共同月份只按每来源是否有线索确定，不按签约数筛选。
-- 权重目标：共同月份内这三来源合并后的样本月份构成。

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
),
all_counts AS (
    SELECT channel, SUM(lead_count) AS all_lead_count, SUM(won_count) AS all_won_count
    FROM monthly
    GROUP BY channel
),
common_results AS (
    SELECT m.channel,
           SUM(m.lead_count) AS common_lead_count,
           SUM(m.won_count) AS common_won_count,
           SUM(w.month_weight * 100.0 * m.won_count / m.lead_count) AS standardized_won_pct,
           COUNT(*) AS common_month_count,
           SUM(m.date_issue_count) AS common_date_issue_count
    FROM monthly AS m
    JOIN weights AS w ON m.contact_month = w.contact_month
    GROUP BY m.channel
)
SELECT a.channel,
       a.all_lead_count,
       a.all_won_count,
       100.0 * a.all_won_count / a.all_lead_count AS all_observed_won_pct,
       c.common_lead_count,
       c.common_won_count,
       100.0 * c.common_won_count / c.common_lead_count AS common_observed_won_pct,
       c.standardized_won_pct,
       c.common_month_count,
       (SELECT SUM(pooled_lead_count) FROM pooled_months) AS shared_weight_lead_count,
       c.common_date_issue_count
FROM all_counts AS a
JOIN common_results AS c ON a.channel = c.channel
ORDER BY a.channel;
