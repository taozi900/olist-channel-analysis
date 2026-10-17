"""第九步：用SQL定位来源标签问题，生成独立报告和一张诊断图。

本文件放项目根目录，三个09开头SQL放sql文件夹；点击运行。
复用04的来源校验和07的绘图样式；只读SQLite，不修改01—08结果。
"""

import csv
import hashlib
import importlib.util
import json
import math
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / 'reports'
FIGURES = REPORTS / 'figures'
DB = ROOT / 'data' / 'olist_marketing.sqlite3'
COUNTS = ['lead_count', 'unknown_count', 'blank_count', 'other_label_count']
PCTS = ['unknown_pct', 'blank_pct', 'unclear_pct']
QUERIES = {
    'pages': ('09_landing_source_pages.sql', ['landing_page_id'] + COUNTS + PCTS),
    'sources': ('09_landing_page_sources.sql', ['landing_page_id', 'channel', 'lead_count']),
    'months': ('09_landing_source_months.sql', ['contact_month', 'landing_page_id'] + COUNTS + PCTS),
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pct(n, d):
    if not d:
        return '—'
    return str((Decimal(n) * 100 / Decimal(d)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def count_row(group, values):
    n, unknown, blank = values
    return {**group, 'lead_count': n, 'unknown_count': unknown, 'blank_count': blank,
            'other_label_count': n - unknown - blank, 'unknown_pct': 100 * unknown / n,
            'blank_pct': 100 * blank / n, 'unclear_pct': 100 * (unknown + blank) / n}


def reference_from_csv(leads):
    pages = defaultdict(lambda: [0, 0, 0])
    months = defaultdict(lambda: [0, 0, 0])
    sources = Counter()
    for lead in leads:
        page = lead['landing_page_id'].strip() or '(落地页未记录)'
        channel = lead['origin'].strip() or '(未记录)'
        month = lead['first_contact_date'][:7]
        for counts in [pages[page], months[(month, page)]]:
            counts[0] += 1
            counts[1] += int(channel == 'unknown')
            counts[2] += int(channel == '(未记录)')
        sources[(page, channel)] += 1
    return {
        'pages': {page: count_row({'landing_page_id': page}, values) for page, values in pages.items()},
        'months': {key: count_row({'contact_month': key[0], 'landing_page_id': key[1]}, values) for key, values in months.items()},
        'sources': {key: {'landing_page_id': key[0], 'channel': key[1], 'lead_count': n} for key, n in sources.items()},
    }


def execute_and_verify(hashes, expected):
    results = {}
    with closing(sqlite3.connect(DB.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA query_only = ON')
        metadata = dict(conn.execute('SELECT key, value FROM project_metadata'))
        if metadata.get('schema_version') != 'olist_stage02_v1' or any(metadata.get('sha256:' + name) != digest for name, digest in hashes.items()):
            raise ValueError('数据库版本或来源不一致，请先核对02报告。')
        conn.row_factory = sqlite3.Row
        for key, (filename, columns) in QUERIES.items():
            path = ROOT / 'sql' / filename
            sql = path.read_text(encoding='utf-8-sig').strip()
            cursor = conn.execute(sql)
            if cursor.description is None or [x[0] for x in cursor.description] != columns:
                raise ValueError(f'{filename}的输出列名与本步口径不符。')
            rows = [dict(r) for r in cursor.fetchall()]
            found = set()
            for row in rows:
                group = row['landing_page_id'] if key == 'pages' else ((row['contact_month'], row['landing_page_id']) if key == 'months' else (row['landing_page_id'], row['channel']))
                if group in found or group not in expected[key]:
                    raise ValueError(f'{filename}存在重复或不符合原始CSV的分组。')
                found.add(group)
                reference = expected[key][group]
                for field, value in reference.items():
                    actual = row[field]
                    if field in PCTS:
                        if not isinstance(actual, (int, float)) or not math.isclose(actual, value, abs_tol=1e-10, rel_tol=1e-12):
                            raise ValueError(f'{filename}比例与原始CSV不一致。')
                    elif actual != value or (isinstance(value, int) and type(actual) is not int):
                        raise ValueError(f'{filename}分组或计数与原始CSV不一致。')
            if found != set(expected[key]):
                raise ValueError(f'{filename}遗漏了原始CSV中的分组。')
            results[key] = {'file': str(path), 'sha256': sha256(path), 'executed_sql': sql, 'rows': rows}
    return results


def summarize(queries):
    pages = queries['pages']['rows']
    aliases = {r['landing_page_id']: f'页{i:03d}' for i, r in enumerate(sorted(pages, key=lambda r: (-r['lead_count'], r['landing_page_id'])), 1)}
    totals = {field: sum(r[field] for r in pages) for field in COUNTS}
    concentration = {}
    for label, field in [('unknown', 'unknown_count'), ('blank', 'blank_count')]:
        ordered = sorted((r for r in pages if r[field] > 0), key=lambda r: (-r[field], r['landing_page_id']))
        concentration[label] = {'page_count': len(ordered), 'count': totals[field], 'top': []}
        for k in [1, 3, 5, 10]:
            count = sum(r[field] for r in ordered[:k])
            concentration[label]['top'].append({'k': k, 'count': count, 'share_pct': 100 * count / totals[field] if totals[field] else None})
    ordered_unknown = sorted(pages, key=lambda r: (-r['unknown_count'], r['landing_page_id']))
    if not ordered_unknown or totals['unknown_count'] == 0:
        raise ValueError('本数据没有unknown标签，本步目标页规则不适用。')
    target = ordered_unknown[0]
    target_months = [r for r in queries['months']['rows'] if r['landing_page_id'] == target['landing_page_id']]
    if any(sum(r[f] for r in target_months) != target[f] for f in COUNTS):
        raise ValueError('目标页月度计数无法对齐汇总。')
    return totals, aliases, concentration, target, target_months


def draw_figure(queries, totals, aliases, concentration, target, months):
    plot = load_module('olist_plot_style09', '07_plot_project.py')
    family = plot.configure_style()
    plt = plot.plt
    fig = plt.figure(figsize=(14, 8.4))
    fig.text(.055, .955, '来源标签诊断：先定位unknown集中的落地页', fontsize=20, weight='bold', va='top')
    fig.text(.055, .90, f"{totals['lead_count']:,}条MQL记录｜{len(aliases)}个匿名落地页ID｜unknown与来源空白分别统计", fontsize=10.5, color=plot.MUTED)
    gs = fig.add_gridspec(1, 2, left=.10, right=.96, top=.78, bottom=.31, wspace=.35, width_ratios=[1, 1.4])
    left, right = fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1])
    top = sorted((r for r in queries['pages']['rows'] if r['unknown_count']), key=lambda r: (-r['unknown_count'], r['landing_page_id']))[:5]
    labels = [aliases[r['landing_page_id']] for r in top] + ['其余页面合计']
    values = [r['unknown_count'] for r in top] + [totals['unknown_count'] - sum(r['unknown_count'] for r in top)]
    left.barh(range(len(values)), values, color=['#C17C3A'] + ['#A4B9C1'] * (len(values)-1), height=.58)
    left.set_yticks(range(len(labels)), labels)
    left.invert_yaxis()
    left.set_xlim(0, max(values) * 1.38)
    left.set_xlabel('unknown记录数（条）')
    left.set_title('左图：unknown在哪些页面集中？', fontsize=12, weight='bold', pad=15)
    for i, n in enumerate(values):
        left.text(n + max(values)*.02, i, f"{n}（{pct(n, totals['unknown_count'])}%）", va='center', fontsize=9)
    plot.clean_axis(left)
    xs = range(len(months))
    known = [r['other_label_count'] for r in months]
    unknown = [r['unknown_count'] for r in months]
    blank = [r['blank_count'] for r in months]
    right.bar(xs, known, color='#A4B9C1', label='其他已记录来源', width=.7)
    right.bar(xs, unknown, bottom=known, color='#C17C3A', label='unknown', width=.7)
    right.bar(xs, blank, bottom=[a+b for a,b in zip(known, unknown)], color='#B64C5E', label='来源空白', width=.7)
    right.set_xticks(list(xs), [r['contact_month'] for r in months], rotation=45, ha='right', fontsize=8.5)
    right.set_ylabel('目标页线索记录数（条）')
    right.set_title(f"右图：{aliases[target['landing_page_id']]}的月度来源构成", fontsize=12, weight='bold', pad=15)
    right.set_ylim(0, max(r['lead_count'] for r in months)*1.20)
    for i, row in enumerate(months):
        right.text(i, row['lead_count']+2, str(row['lead_count']), ha='center', fontsize=8)
    right.legend(loc='upper left', frameon=False, fontsize=8.2)
    plot.clean_axis(right, grid='y')
    fig.text(.06, .195, f"优先回查 {aliases[target['landing_page_id']]}：unknown {target['unknown_count']}条，占全部unknown的{pct(target['unknown_count'], totals['unknown_count'])}%", fontsize=12, weight='bold')
    fig.text(.06, .15, f"该页共{target['lead_count']}条：unknown {target['unknown_count']}，空白{target['blank_count']}，其他标签{target['other_label_count']}。空白来源全样本分布在{concentration['blank']['page_count']}个页ID。", fontsize=10.3)
    fig.text(.06, .085, '左图括号分母是全部unknown；右图柱高是目标页月内总数。页面别名与原始ID对应表见09报告。', fontsize=9.1, color=plot.MUTED)
    fig.text(.06, .05, '仅定位回查对象；匿名ID不对应已知URL，尚未确认采集故障或修复效果。来源：Olist公开抽样CSV及本步SQL。', fontsize=9.1, color=plot.MUTED)
    FIGURES.mkdir(parents=True, exist_ok=True)
    stem = FIGURES / '09_01_landing_source_diagnosis'
    fig.savefig(stem.with_suffix('.png'), dpi=180, metadata={'Software': 'Olist source quality diagnosis'})
    fig.savefig(stem.with_suffix('.svg'), metadata={'Date': None})
    plt.close(fig)
    return family, [stem.with_suffix('.png'), stem.with_suffix('.svg')]


def report_text(queries, totals, aliases, concentration, target, months):
    page = target['landing_page_id']
    lines = ['# 第九步：来源标签与落地页诊断', '', '## 核心发现', '',
        f"共{totals['lead_count']:,}条线索、{len(aliases)}个匿名落地页ID。unknown有{totals['unknown_count']:,}条，来源空白{totals['blank_count']}条，两类分别分析。", '',
        f"按unknown记录数排序，优先回查{aliases[page]}（原始ID：`{page}`）。它有{target['unknown_count']}条unknown，占全部unknown的{pct(target['unknown_count'], totals['unknown_count'])}%；这表示问题线索集中位置，不代表已确认故障。", '',
        f"该页共{target['lead_count']}条线索，unknown {target['unknown_count']}条、空白{target['blank_count']}条、其他已记录来源{target['other_label_count']}条。页内unknown占比{pct(target['unknown_count'], target['lead_count'])}%；unknown与空白合计占比{pct(target['unknown_count']+target['blank_count'], target['lead_count'])}%。不要混淆以上不同分母。", '',
        '## unknown与空白的集中程度', '',
        '| 标签类别 | 记录数 | 涉及页ID数 | Top1占该类 | Top3占该类 | Top5占该类 | Top10占该类 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for key, label in [('unknown', 'unknown'), ('blank', '来源空白')]:
        c = concentration[key]
        shares = [pct(x['count'], c['count'])+'%' for x in c['top']]
        lines.append('| ' + ' | '.join([label, str(c['count']), str(c['page_count'])] + shares) + ' |')
    lines += ['', '两类的页面分布不同，不能自动认定为同一根因。没有按签约表现挑选目标页，也没有把小分母高比例页面排成效果赢家。', '',
        '## 目标页按首次联系月份拆分', '',
        '| 月份 | 线索数 | unknown | 空白 | 其他已记录来源 | 页内unknown占比 |', '| --- | ---: | ---: | ---: | ---: | ---: |']
    for r in months:
        lines.append(f"| {r['contact_month']} | {r['lead_count']} | {r['unknown_count']} | {r['blank_count']} | {r['other_label_count']} | {pct(r['unknown_count'], r['lead_count'])}% |")
    lines += ['', '只展示目标页有线索的月份；没有线索的月份不补0%比例。unknown数量变化要结合月内总量与占比，不能把计数增加直接归因为采集故障加重。', '',
        '## 建议怎样回查', '',
        '1. 若能取得企业后台，先把此匿名ID映射到真实落地页与表单配置；当前公开数据不包含URL或页面内容。',
        '2. 核对来源标签字典、来源采集／映射规则及历史配置变化，同时分别回查unknown与空白。',
        '3. 补齐原始访问及表单日志后抽样核验，再判断是否属于未分类来源、规则差异或采集问题。', '',
        '以上是待执行的核查建议，没有证明故障根因、实施修复或测得修复收益。该页ID也不等于已经验证的独立页面版本或独立商家。', '',
        '## 图表', '', '![来源标签诊断](figures/09_01_landing_source_diagnosis.png)', '',
        '## 页面别名与完整汇总', '',
        '页面别名按全部线索量从大到小分配，数量相同时按原始ID排序；下面按unknown数量排序。保留所有页面，不删除小样本。', '',
        '| 别名 | 原始匿名ID | 线索数 | unknown | 空白 | 其他标签 | 页内unknown占比 |', '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for r in queries['pages']['rows']:
        lines.append(f"| {aliases[r['landing_page_id']]} | {r['landing_page_id']} | {r['lead_count']} | {r['unknown_count']} | {r['blank_count']} | {r['other_label_count']} | {pct(r['unknown_count'], r['lead_count'])}% |")
    lines += ['', '## SQL与导出', '', '09_landing_source_pages.csv为页面汇总，09_landing_page_sources.csv为页面×来源，09_landing_source_months.csv为月份×页面；CSV和JSON保留未舍入比例。', '']
    for key, (filename, _) in QUERIES.items():
        lines += ['### ' + filename, '', '```sql', queries[key]['executed_sql'], '```', '']
    lines += ['## 学习重点与边界', '',
        '- CASE WHEN分别给unknown和空白打标，SUM汇总数量；GROUP BY同时按页面或页面×月份分组。',
        '- 左图集中度的分母是全样本unknown；页内unknown占比的分母是该页全部线索。',
        '- “其他已记录来源”只是非空、非unknown的原始标签，没有进行独立真实性审计。',
        '- 当前是来源标签数据质量诊断，不是马尔科夫链归因、页面转化因果效果或预算优化。',
        '- 原CSV、数据库、你修改的03 SQL及01—08结果保持不变；10稳健性分析是下一步。', '',
        '数据来源与许可见[data/raw/SOURCE.md](../data/raw/SOURCE.md)。', '']
    return '\n'.join(lines)


def main():
    stage04 = load_module('olist_stage04_for09', '04_channel_metrics.py')
    tables, hashes = stage04.read_sources()
    if not DB.is_file():
        raise ValueError('找不到SQLite数据库，请先运行02。')
    protected = [DB] + list((ROOT/'data/raw').glob('*')) + list((ROOT/'sql').glob('*.sql'))
    protected += [p for p in REPORTS.rglob('*') if p.is_file() and not p.name.startswith('09_')]
    protected = [p for p in protected if p.is_file()]
    before = {str(p): sha256(p) for p in protected}
    expected = reference_from_csv(tables[stage04.MQL_FILE])
    queries = execute_and_verify(hashes, expected)
    totals, aliases, concentration, target, months = summarize(queries)
    family, images = draw_figure(queries, totals, aliases, concentration, target, months)
    REPORTS.mkdir(parents=True, exist_ok=True)
    md = REPORTS/'09_来源标签与落地页诊断.md'
    md.write_text(report_text(queries, totals, aliases, concentration, target, months), encoding='utf-8')
    for key, (filename, columns) in QUERIES.items():
        with (REPORTS/Path(filename).with_suffix('.csv').name).open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(queries[key]['rows'])
    if any(sha256(Path(path)) != digest for path, digest in before.items()):
        raise ValueError('受保护的原始文件、数据库或早期结果发生变化，请检查。')
    result = {'stage': '09_landing_source_quality_diagnosis', 'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_sha256': hashes, 'database_sha256': sha256(DB), 'original_files_and_01_to_08_unchanged': True,
        'sql_counts_match_independent_raw_counts': True,
        'target_rule': '按unknown_count降序、匿名ID升序选首位；不使用签约结果挑选。',
        'totals': totals, 'page_aliases': aliases, 'concentration': concentration, 'target_page': target,
        'target_months': months, 'queries': queries, 'font_family': family,
        'outputs': {str(p.relative_to(ROOT)).replace('\\', '/'): {'bytes': p.stat().st_size, 'sha256': sha256(p)} for p in images+[md]}}
    (REPORTS/'09_landing_source_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('第九步完成：来源标签与落地页诊断已生成。')
    print(f"全部线索{totals['lead_count']:,}条；unknown {totals['unknown_count']:,}条；来源空白{totals['blank_count']}条，分别保留。")
    print(f"unknown分布在{concentration['unknown']['page_count']}个页ID，空白分布在{concentration['blank']['page_count']}个页ID。")
    print(f"优先回查{aliases[target['landing_page_id']]}：{target['landing_page_id']}")
    print(f"该页unknown {target['unknown_count']}条，占全部unknown的{pct(target['unknown_count'], totals['unknown_count'])}%；该页全部线索{target['lead_count']}条。")
    print(f"该页来源空白{target['blank_count']}条；unknown与空白合计占该页{pct(target['unknown_count']+target['blank_count'], target['lead_count'])}%。")
    print('SQL结果已与原始CSV逐组核对；原CSV、数据库、03练习SQL及01—08结果保持不变。')
    print(f'报告：{md}')
    print(f'图片：{images[0]}')
    print('请截图终端结果，下一步做第十步稳健性分析。')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        raise SystemExit(f'第九步未完成：{exc}\n请检查04、07脚本与三个09 SQL是否放在原项目相应目录。') from exc
