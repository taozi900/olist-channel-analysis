"""第三步：运行独立SQL文件，练习按首次联系月份统计线索。

复制本文件和sql文件夹到项目根目录，与01、02脚本同级。
修改sql/03_monthly_leads.sql后保存，再点本文件右上角的运行按钮。
只用Python标准库，以只读模式打开02已经创建的数据库。
"""

import csv
import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "olist_marketing.sqlite3"
SQL_FILE = ROOT / "sql" / "03_monthly_leads.sql"
RAW = ROOT / "data" / "raw"
MQL_FILE = "olist_marketing_qualified_leads_dataset.csv"
REPORTS = ROOT / "reports"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_month_counts():
    manifest = json.loads((RAW / "source_manifest.json").read_text(encoding="utf-8"))
    expected_hash = manifest["files"][MQL_FILE]["sha256"]
    if sha256(RAW / MQL_FILE) != expected_hash:
        raise ValueError("营销线索CSV与下载清单不一致，请先检查原始数据。")
    # CSV计数只用于独立核对；报告中的月份分布由SQL实际执行产生。
    with (RAW / MQL_FILE).open(encoding="utf-8-sig", newline="") as f:
        counts = Counter(row["first_contact_date"][:7] for row in csv.DictReader(f))
    return expected_hash, counts


def run_query(source_hash):
    if not DB.is_file():
        raise ValueError("找不到数据库，请先运行02_build_database.py。")
    if not SQL_FILE.is_file():
        raise ValueError("找不到sql/03_monthly_leads.sql，请把sql文件夹放到03脚本旁边。")
    sql = SQL_FILE.read_text(encoding="utf-8-sig").strip()
    if not sql:
        raise ValueError("SQL文件为空，请先写入查询并保存。")
    with closing(sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only = ON")
        metadata = dict(conn.execute("SELECT key, value FROM project_metadata"))
        if metadata.get("schema_version") != "olist_stage02_v1" or metadata.get(f"sha256:{MQL_FILE}") != source_hash:
            raise ValueError("数据库的来源与版本不匹配，请先检查02运行结果。")
        cursor = conn.execute(sql)
        if cursor.description is None:
            raise ValueError("本步需要一条返回月份和线索数的查询。")
        columns = [item[0] for item in cursor.description]
        if columns != ["contact_month", "lead_count"]:
            raise ValueError("本练习需要两列：contact_month、lead_count。请保留这两个列名。")
        rows = cursor.fetchmany(501)
        if len(rows) > 500:
            raise ValueError("结果超过500行，请检查是否遗漏GROUP BY；本题应按月份汇总。")
    return sql, [{"contact_month": month, "lead_count": count} for month, count in rows]


def check_result(rows, expected):
    if any(not isinstance(r["contact_month"], str) or type(r["lead_count"]) is not int or r["lead_count"] <= 0 for r in rows):
        raise ValueError("月份应为文本，线索数应为正整数，请检查SQL。")
    actual = {r["contact_month"]: r["lead_count"] for r in rows}
    if len(actual) != len(rows) or actual != dict(expected):
        raise ValueError("SQL结果与原始线索的月份分布不一致，请检查分组或筛选条件。")
    return sum(r["lead_count"] for r in rows)


def write_report(result):
    lines = [
        "# 第三步：用独立SQL按月统计线索", "",
        "统计单位：抽样数据中的MQL线索记录。分组日期：首次联系日期，不是签约日期。", "",
        "## 实际执行的SQL", "", "```sql", result["executed_sql"], "```", "",
        "## 执行结果", "", "| 首次联系月份 | 线索记录数 |", "| --- | ---: |",
    ]
    for row in result["rows"]:
        lines.append(f"| {row['contact_month']} | {row['lead_count']} |")
    lines.extend([
        f"| 合计 | {result['total_lead_count']} |", "",
        f"结果覆盖{len(result['rows'])}个月，与原始CSV月份分布核对一致。数据库及原始CSV保持不变。", "",
        "## 逐句阅读", "",
        "- SELECT：选择要展示的列。",
        "- SUBSTR(first_contact_date, 1, 7)：截取日期前7个字符，得到年和月。",
        "- AS contact_month：给这一列起名，便于阅读和排序。",
        "- COUNT(*)：每组有多少条线索记录。",
        "- FROM mql：从营销线索表取数。",
        "- GROUP BY：同一年月的线索分到一组。",
        "- ORDER BY：排列结果；ASC表示从小到大，DESC表示从大到小。", "",
        "## 动手改一次排序", "",
        "在sql/03_monthly_leads.sql里，把最后一行改成：", "",
        "```sql", "ORDER BY lead_count DESC, contact_month ASC;", "```", "",
        "按Ctrl+S保存SQL文件，再运行03_run_sql.py。第一行会显示线索数最多的月份；各月数量与合计应保持相同。", "",
        "## 本步能说明什么", "",
        "此表描述本批样本在首次联系月份上的分布。样本月度数量不直接等于企业完整月度获客总量，首月覆盖是否完整也未知。",
        "本步不计算签约率，不把线索量最多解释为渠道效果最好，也不把样本月份差异归因为某次营销活动。",
    ])
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "03_月度线索SQL结果.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (REPORTS / "03_monthly_leads.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    source_hash, expected = source_month_counts()
    if not DB.is_file():
        raise ValueError("找不到数据库，请先运行02_build_database.py。")
    db_before = sha256(DB)
    sql, rows = run_query(source_hash)
    total = check_result(rows, expected)
    if sha256(DB) != db_before or sha256(RAW / MQL_FILE) != source_hash:
        raise ValueError("运行期间数据库或原始数据发生变化，请先核对。")
    result = {
        "stage": "03_monthly_leads_sql_practice",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "database": str(DB),
        "database_sha256": db_before,
        "source_mql_sha256": source_hash,
        "sql_file": str(SQL_FILE),
        "sql_sha256": sha256(SQL_FILE),
        "executed_sql": sql,
        "rows": rows,
        "total_lead_count": total,
        "monthly_counts_match_source": True,
        "database_and_raw_mql_unchanged": True,
    }
    write_report(result)
    print("第三步完成：已执行独立SQL文件。")
    print(f"SQL文件：{SQL_FILE}")
    print("\n首次联系月份 | 线索记录数")
    for row in rows:
        print(f"  {row['contact_month']} | {row['lead_count']:,}")
    print(f"合计：{total:,}条，覆盖{len(rows)}个月；与原始CSV核对一致。")
    print("统计的是样本线索量，不是签约数或企业完整月度获客量。")
    print(f"报告：{REPORTS / '03_月度线索SQL结果.md'}")
    print("先截图运行结果；随后可以自己修改SQL最后一行的排序。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        raise SystemExit(f"第三步未完成：{exc}\n请确认SQL已经保存，且01、02已运行成功。") from exc
