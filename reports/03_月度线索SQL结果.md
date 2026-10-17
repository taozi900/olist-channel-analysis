# 第三步：用独立SQL按月统计线索

统计单位：抽样数据中的MQL线索记录。分组日期：首次联系日期，不是签约日期。

## 实际执行的SQL

```sql
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
```

## 执行结果

| 首次联系月份 | 线索记录数 |
| --- | ---: |
| 2018-04 | 1352 |
| 2018-05 | 1303 |
| 2018-03 | 1174 |
| 2018-01 | 1141 |
| 2018-02 | 1028 |
| 2017-11 | 445 |
| 2017-10 | 416 |
| 2017-08 | 386 |
| 2017-09 | 312 |
| 2017-07 | 239 |
| 2017-12 | 200 |
| 2017-06 | 4 |
| 合计 | 8000 |

结果覆盖12个月，与原始CSV月份分布核对一致。数据库及原始CSV保持不变。

## 逐句阅读

- SELECT：选择要展示的列。
- SUBSTR(first_contact_date, 1, 7)：截取日期前7个字符，得到年和月。
- AS contact_month：给这一列起名，便于阅读和排序。
- COUNT(*)：每组有多少条线索记录。
- FROM mql：从营销线索表取数。
- GROUP BY：同一年月的线索分到一组。
- ORDER BY：排列结果；ASC表示从小到大，DESC表示从大到小。

## 动手改一次排序

在sql/03_monthly_leads.sql里，把最后一行改成：

```sql
ORDER BY lead_count DESC, contact_month ASC;
```

按Ctrl+S保存SQL文件，再运行03_run_sql.py。第一行会显示线索数最多的月份；各月数量与合计应保持相同。

## 本步能说明什么

此表描述本批样本在首次联系月份上的分布。样本月度数量不直接等于企业完整月度获客总量，首月覆盖是否完整也未知。
本步不计算签约率，不把线索量最多解释为渠道效果最好，也不把样本月份差异归因为某次营销活动。
