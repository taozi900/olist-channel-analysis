# 第二步：SQLite导入与入门SQL

数据库：`olist_marketing.sqlite3`，位于项目的data文件夹。状态：创建新数据库。

CSV空值入库为NULL；原始字符串unknown单独保留。所有原始字段按TEXT保存，0.0和False不会转为NULL。
原始CSV和第一步报告保持不变。本次仅做数量核对，不比较渠道签约率。

## 用来连接两表的SQL

```sql
-- 以全部营销线索为起点，保留未匹配签约记录的线索。
CREATE VIEW lead_overview AS
SELECT
    m.mql_id,
    m.first_contact_date,
    SUBSTR(m.first_contact_date, 1, 7) AS first_contact_month,
    m.landing_page_id,
    m.origin,
    COALESCE(NULLIF(TRIM(m.origin), ''), '(未记录)') AS origin_group,
    c.seller_id,
    c.won_date,
    CASE WHEN c.mql_id IS NOT NULL THEN 1 ELSE 0 END AS has_observed_won,
    CASE WHEN DATE(c.won_date) < DATE(m.first_contact_date) THEN 1 ELSE 0 END AS date_order_issue
FROM mql AS m
LEFT JOIN closed_deals AS c
    ON m.mql_id = c.mql_id;
```

## 1. 两张原始表各有多少记录？

```sql
SELECT 'mql' AS table_name,
       COUNT(*) AS row_count,
       COUNT(DISTINCT mql_id) AS distinct_mql_count
FROM mql
UNION ALL
SELECT 'closed_deals', COUNT(*), COUNT(DISTINCT mql_id)
FROM closed_deals;
```

| table_name | row_count | distinct_mql_count |
| --- | --- | --- |
| mql | 8000 | 8000 |
| closed_deals | 842 | 842 |

## 2. LEFT JOIN后是否保留了全部线索？

```sql
SELECT COUNT(*) AS lead_count,
       SUM(has_observed_won) AS observed_won_count,
       SUM(1 - has_observed_won) AS no_observed_won_count,
       SUM(date_order_issue) AS date_issue_count
FROM lead_overview;
```

| lead_count | observed_won_count | no_observed_won_count | date_issue_count |
| --- | --- | --- | --- |
| 8000 | 842 | 7158 | 1 |

## 3. 各渠道带来多少线索？占全部线索多少？

```sql
SELECT origin_group AS channel,
       COUNT(*) AS lead_count,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM lead_overview), 2) AS lead_share_pct
FROM lead_overview
GROUP BY origin_group
ORDER BY lead_count DESC, channel;
```

| channel | lead_count | lead_share_pct |
| --- | --- | --- |
| organic_search | 2296 | 28.7 |
| paid_search | 1586 | 19.83 |
| social | 1350 | 16.88 |
| unknown | 1099 | 13.74 |
| direct_traffic | 499 | 6.24 |
| email | 493 | 6.16 |
| referral | 284 | 3.55 |
| other | 150 | 1.88 |
| display | 118 | 1.48 |
| other_publicities | 65 | 0.81 |
| (未记录) | 60 | 0.75 |

## 先理解这几个词

- LEFT JOIN：以左边的线索表为起点；右边没有签约匹配的线索也保留。
- COUNT(*)：统计当前查询结果的行数。连接结果有8,000行，不能把它全部叫签约数。
- CASE：根据是否匹配到签约ID生成0／1标志。has_observed_won为0只代表未观察到签约。
- GROUP BY：按渠道分组，各组分别数线索。
- lead_share_pct：该渠道线索数占全部线索的比例，不是签约率，也不是渠道效果。
- unknown是原始文本标签，(未记录)对应原CSV空渠道；两类分别保留。

唯一日期冲突仍在数据库中，date_order_issue标记为1，没有删除或修正。

## 下一步要自己练习

1. 用自己的话解释为什么这里使用LEFT JOIN。
2. 找到渠道分组查询，指出哪一行负责分组、哪一行负责排序。
3. 后续用独立SQL文件练习按首次联系月份统计，再定义观测签约指标与观察窗口。

此阶段完成了取数与连接核对，尚未得出渠道表现优劣或预算建议。
