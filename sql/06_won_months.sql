-- 这次按“签约发生月份”统计，含日期冲突原记录。
-- 与04按“首次联系月份”分组的指标，含义不同。

SELECT
    SUBSTR(won_date, 1, 7) AS won_month,
    COUNT(*) AS observed_won_count
FROM lead_overview
WHERE has_observed_won = 1
GROUP BY SUBSTR(won_date, 1, 7)
ORDER BY won_month ASC;
