"""第二步：导入SQLite，用SQL核对连接和渠道线索分布。

与01_read_and_audit.py放在同一级，点击VS Code右上角运行按钮。
仅使用Python标准库。数据库：data/olist_marketing.sqlite3。
原始CSV不修改；重复运行会检查并复用本脚本创建的数据库。
"""

import importlib.util
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "olist_marketing.sqlite3"
REPORTS = ROOT / "reports"
SCHEMA_VERSION = "olist_stage02_v1"

# 原始字段按TEXT入库，保留ID、日期和分类标签的原始写法。
# CSV空字段转为SQL NULL；数值文本0.0、布尔文本False仍保留。
SCHEMA_SQL = """
CREATE TABLE project_metadata (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
CREATE TABLE mql (
    mql_id TEXT PRIMARY KEY NOT NULL,
    first_contact_date TEXT NOT NULL,
    landing_page_id TEXT,
    origin TEXT
);
CREATE TABLE closed_deals (
    mql_id TEXT PRIMARY KEY NOT NULL REFERENCES mql(mql_id),
    seller_id TEXT,
    sdr_id TEXT,
    sr_id TEXT,
    won_date TEXT NOT NULL,
    business_segment TEXT,
    lead_type TEXT,
    lead_behaviour_profile TEXT,
    has_company TEXT,
    has_gtin TEXT,
    average_stock TEXT,
    business_type TEXT,
    declared_product_catalog_size TEXT,
    declared_monthly_revenue TEXT
);

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
"""

# 本步执行的三条SELECT；报告也会保存原文，方便逐句学习。
QUERIES = [
    ("table_counts", "1. 两张原始表各有多少记录？", """
SELECT 'mql' AS table_name,
       COUNT(*) AS row_count,
       COUNT(DISTINCT mql_id) AS distinct_mql_count
FROM mql
UNION ALL
SELECT 'closed_deals', COUNT(*), COUNT(DISTINCT mql_id)
FROM closed_deals;
"""),
    ("join_counts", "2. LEFT JOIN后是否保留了全部线索？", """
SELECT COUNT(*) AS lead_count,
       SUM(has_observed_won) AS observed_won_count,
       SUM(1 - has_observed_won) AS no_observed_won_count,
       SUM(date_order_issue) AS date_issue_count
FROM lead_overview;
"""),
    ("channel_counts", "3. 各渠道带来多少线索？占全部线索多少？", """
SELECT origin_group AS channel,
       COUNT(*) AS lead_count,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM lead_overview), 2) AS lead_share_pct
FROM lead_overview
GROUP BY origin_group
ORDER BY lead_count DESC, channel;
"""),
]


def load_stage01():
    script = ROOT / "01_read_and_audit.py"
    spec = importlib.util.spec_from_file_location("olist_stage01", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    prior = json.loads((REPORTS / "01_data_audit.json").read_text(encoding="utf-8"))
    if prior.get("stage") != "01_source_and_structure_audit":
        raise ValueError("请先运行01_read_and_audit.py，生成第一步检查报告。")
    fresh = module.run_audit()
    if prior["source"]["files"] != fresh["source"]["files"]:
        raise ValueError("当前来源清单与第一步报告不同，请先重新检查数据。")
    # 已知日期冲突保留标记；它不妨碍将原始记录完整入库。
    required = ["join_keys_nonempty_and_unique", "all_won_records_have_lead_match", "all_dates_present_and_parseable", "raw_csv_unchanged"]
    if not all(fresh["checks"][name] for name in required):
        raise ValueError("键、连接覆盖或日期解析存在异常，请先检查01报告。")
    return module, fresh


def as_sql_values(columns, rows):
    return [tuple(None if not row[c].strip() else row[c] for c in columns) for row in rows]


def read_source_tables(stage01):
    result = {}
    for table, filename in [("mql", stage01.MQL_FILE), ("closed_deals", stage01.DEAL_FILE)]:
        columns, rows = stage01.read_table(filename)
        result[table] = (columns, as_sql_values(columns, rows))
    return result


def verify_database(connection, tables, metadata):
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise ValueError("数据库完整性检查未通过。")
    stored = dict(connection.execute("SELECT key, value FROM project_metadata"))
    if stored != metadata:
        raise ValueError("现有数据库来源或版本不一致；已保留原文件，请先核对。")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("数据库存在找不到对应线索的签约记录。")
    for table, (columns, values) in tables.items():
        actual = connection.execute(f'SELECT * FROM "{table}" ORDER BY mql_id').fetchall()
        expected = sorted(values, key=lambda row: row[0])
        if actual != expected:
            raise ValueError(f"数据库{table}表与原始CSV不一致；已保留数据库，请先核对。")


def build_or_reuse_database(tables, metadata):
    if DB.exists():
        # 已有数据库只读检查，不删除、不重建，保留后续学习时增加的表。
        with closing(sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            verify_database(connection, tables, metadata)
        return "复用现有数据库"

    DB.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=".olist_stage02_", suffix=".sqlite3", dir=DB.parent)
    os.close(handle)
    temporary = Path(temp_name)
    try:
        connection = sqlite3.connect(temporary)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(SCHEMA_SQL)
            with connection:
                connection.executemany("INSERT INTO project_metadata VALUES (?, ?)", sorted(metadata.items()))
                for table, (columns, values) in tables.items():
                    placeholders = ", ".join("?" for _ in columns)
                    connection.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', values)
            verify_database(connection, tables, metadata)
        finally:
            connection.close()
        if DB.exists():
            raise ValueError("目标数据库已被其他操作创建，已停止替换；请重新运行检查。")
        temporary.replace(DB)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "创建新数据库"


def query_database():
    result = {}
    with closing(sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        for key, title, sql in QUERIES:
            result[key] = {"title": title, "sql": sql.strip(), "rows": [dict(row) for row in connection.execute(sql)]}
    return result


def verify_results(results, audit, stage01):
    counts = {row["table_name"]: row for row in results["table_counts"]["rows"]}
    expected_leads = audit["tables"][stage01.MQL_FILE]["rows"]
    expected_deals = audit["tables"][stage01.DEAL_FILE]["rows"]
    if counts["mql"]["row_count"] != expected_leads or counts["closed_deals"]["row_count"] != expected_deals:
        raise ValueError("导入数量与原始数据不一致。")
    joined = results["join_counts"]["rows"][0]
    expected_join = {
        "lead_count": expected_leads,
        "observed_won_count": audit["join"]["matched_distinct_mql_ids"],
        "no_observed_won_count": audit["join"]["unmatched_lead_ids"],
        "date_issue_count": audit["date_order_check"]["won_before_contact_calendar_date_rows"],
    }
    if joined != expected_join:
        raise ValueError("连接结果与第一步检查不一致，请检查lead_overview视图。")
    channels = {row["channel"]: row["lead_count"] for row in results["channel_counts"]["rows"]}
    if channels != audit["origin_lead_counts"]:
        raise ValueError("SQL渠道分组与原始数据检查不一致。")


def write_reports(result):
    REPORTS.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 第二步：SQLite导入与入门SQL", "",
        f"数据库：`{DB.name}`，位于项目的data文件夹。状态：{result['database_action']}。", "",
        "CSV空值入库为NULL；原始字符串unknown单独保留。所有原始字段按TEXT保存，0.0和False不会转为NULL。",
        "原始CSV和第一步报告保持不变。本次仅做数量核对，不比较渠道签约率。", "",
        "## 用来连接两表的SQL", "", "```sql",
        SCHEMA_SQL[SCHEMA_SQL.index("-- 以全部营销线索"):].strip(), "```", "",
    ]
    for key, title, sql in QUERIES:
        rows = result["queries"][key]["rows"]
        lines.extend([f"## {title}", "", "```sql", sql.strip(), "```", ""])
        if rows:
            columns = list(rows[0])
            lines.extend(["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"])
            for row in rows:
                lines.append("| " + " | ".join(str(row[c]) for c in columns) + " |")
            lines.append("")
    lines.extend([
        "## 先理解这几个词", "",
        "- LEFT JOIN：以左边的线索表为起点；右边没有签约匹配的线索也保留。",
        "- COUNT(*)：统计当前查询结果的行数。连接结果有8,000行，不能把它全部叫签约数。",
        "- CASE：根据是否匹配到签约ID生成0／1标志。has_observed_won为0只代表未观察到签约。",
        "- GROUP BY：按渠道分组，各组分别数线索。",
        "- lead_share_pct：该渠道线索数占全部线索的比例，不是签约率，也不是渠道效果。",
        "- unknown是原始文本标签，(未记录)对应原CSV空渠道；两类分别保留。", "",
        "唯一日期冲突仍在数据库中，date_order_issue标记为1，没有删除或修正。", "",
        "## 下一步要自己练习", "",
        "1. 用自己的话解释为什么这里使用LEFT JOIN。",
        "2. 找到渠道分组查询，指出哪一行负责分组、哪一行负责排序。",
        "3. 后续用独立SQL文件练习按首次联系月份统计，再定义观测签约指标与观察窗口。", "",
        "此阶段完成了取数与连接核对，尚未得出渠道表现优劣或预算建议。",
    ])
    (REPORTS / "02_SQL入门结果.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (REPORTS / "02_database_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    stage01, audit = load_stage01()
    tables = read_source_tables(stage01)
    metadata = {"schema_version": SCHEMA_VERSION}
    metadata.update({f"sha256:{name}": value["sha256"] for name, value in audit["source"]["files"].items()})
    action = build_or_reuse_database(tables, metadata)
    queries = query_database()
    verify_results(queries, audit, stage01)
    unchanged = all(stage01.sha256(stage01.RAW / name) == value["sha256"] for name, value in audit["source"]["files"].items())
    if not unchanged:
        raise ValueError("运行中原始文件发生了变化，未生成成功报告，请核对。")
    result = {
        "stage": "02_sqlite_import_and_basic_queries",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "database": str(DB),
        "database_action": action,
        "source_files": audit["source"]["files"],
        "raw_csv_unchanged": unchanged,
        "queries": queries,
    }
    write_reports(result)
    joined = queries["join_counts"]["rows"][0]
    print("第二步完成：SQLite数据库和SQL连接已核对。")
    print(f"数据库：{DB}（{action}）")
    print(f"连接后线索：{joined['lead_count']:,}条；匹配签约：{joined['observed_won_count']:,}条；未匹配签约：{joined['no_observed_won_count']:,}条。")
    print(f"日期冲突保留：{joined['date_issue_count']}条。")
    print("\n渠道线索分布（占比不是签约率）：")
    for row in queries["channel_counts"]["rows"]:
        print(f"  {row['channel']}: {row['lead_count']:,}条，占{row['lead_share_pct']:.2f}%")
    print(f"\nSQL原文和结果：{REPORTS / '02_SQL入门结果.md'}")
    print("请截图终端结果。下一步一起读LEFT JOIN和GROUP BY，再动手写SQL。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        raise SystemExit(f"第二步未完成：{exc}\n请确认本文件与01脚本同级，且01已经运行成功。") from exc
