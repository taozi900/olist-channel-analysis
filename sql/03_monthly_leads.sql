-- 第三步：按首次联系月份，统计样本中的营销线索记录数。
-- SUBSTR(日期, 1, 7)：取YYYY-MM；例如2018-03-08变为2018-03。
-- 先按月份从早到晚排列。运行成功后，可把最后一行改成：
-- ORDER BY lead_count DESC, contact_month ASC;
-- 再运行03_run_sql.py，就能查看线索最多的月份。

SELECT
    SUBSTR(first_contact_date, 1, 7) AS contact_month,
    COUNT(*) AS lead_count
FROM mql
GROUP BY SUBSTR(first_contact_date, 1, 7)
ORDER BY lead_count DESC, contact_month ASC;
