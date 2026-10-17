-- 四种分别比较的设定，不累计叠加；保留05主方案。
-- exclude_date_issue=1：整条异常线索不进入本次分子和分母，再重算权重。
-- minimum_month_n=20：每个来源在该月分别至少20条；不按签约数筛选。
-- equal_month_weight=1：各共同月份等权，改变描述性比较的目标。
WITH settings(scenario, exclude_date_issue, minimum_month_n, equal_month_weight) AS (
    VALUES ('baseline', 0, 1, 0),
           ('exclude_date_issue', 1, 1, 0),
           ('min_month_n20', 0, 20, 0),
           ('equal_months', 0, 1, 1)
),
selected_channels(channel) AS (
    VALUES ('organic_search'), ('paid_search'), ('social')
),
monthly AS (
    SELECT s.scenario, l.first_contact_month AS contact_month,
           l.origin_group AS channel, COUNT(*) AS lead_count,
           SUM(l.has_observed_won) AS observed_won_count,
           SUM(l.date_order_issue) AS date_issue_count
    FROM lead_overview AS l
    CROSS JOIN settings AS s
    WHERE l.origin_group IN (SELECT channel FROM selected_channels)
      AND (s.exclude_date_issue = 0 OR l.date_order_issue = 0)
    GROUP BY s.scenario, l.first_contact_month, l.origin_group
),
common_months AS (
    SELECT m.scenario, m.contact_month
    FROM monthly AS m
    JOIN settings AS s ON m.scenario = s.scenario
    GROUP BY m.scenario, m.contact_month
    HAVING COUNT(*) = (SELECT COUNT(*) FROM selected_channels)
       AND MIN(m.lead_count) >= MAX(s.minimum_month_n)
),
pooled AS (
    SELECT m.scenario, m.contact_month, SUM(m.lead_count) AS pooled_lead_count
    FROM monthly AS m
    JOIN common_months AS c
      ON m.scenario = c.scenario AND m.contact_month = c.contact_month
    GROUP BY m.scenario, m.contact_month
),
weights AS (
    SELECT p.scenario, p.contact_month, p.pooled_lead_count,
           CASE WHEN s.equal_month_weight = 1
                THEN 1.0 / COUNT(*) OVER (PARTITION BY p.scenario)
                ELSE 1.0 * p.pooled_lead_count / SUM(p.pooled_lead_count) OVER (PARTITION BY p.scenario)
           END AS month_weight
    FROM pooled AS p
    JOIN settings AS s ON p.scenario = s.scenario
)
SELECT m.scenario, m.contact_month, m.channel, m.lead_count,
       m.observed_won_count, m.date_issue_count, w.pooled_lead_count,
       w.month_weight,
       100.0 * m.observed_won_count / m.lead_count AS observed_won_pct,
       100.0 * w.month_weight * m.observed_won_count / m.lead_count AS weighted_contribution_pp
FROM monthly AS m
JOIN weights AS w ON m.scenario = w.scenario AND m.contact_month = w.contact_month
ORDER BY m.scenario, m.contact_month, m.channel;
