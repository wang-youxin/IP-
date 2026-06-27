#!/usr/bin/env python3
"""
relationship_analyzer.py — 关系网络分析

全量扫描内容单元的关系网络，输出：
- 关系统计（类型分布、总量）
- 网络中心 Top N（被引用最多的单元）
- 结构洞分析（应连接但未连接的单元群）
- 关系索引 CSV

用法:
  python relationship_analyzer.py <项目目录> [--json] [--csv]

示例:
  python relationship_analyzer.py D:/蒸馏项目/费曼
"""
import sys
from pathlib import Path
from collections import defaultdict, Counter
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import find_unit_files, parse_frontmatter, escape_csv, auto_discover_unit_subdirs


def collect_all_units(base: Path) -> dict[str, dict]:
    """收集所有内容单元。"""
    units = {}
    subdirs = auto_discover_unit_subdirs(base)
    for f in find_unit_files(base, subdirs):
        content = f.read_text(encoding='utf-8')
        fm = parse_frontmatter(content)
        uid = fm.get('id', '')
        if uid:
            units[uid] = {
                'file': str(f.relative_to(base)),
                'type': fm.get('type', Path(f.parent).name),
                'title': fm.get('title', f.stem),
                'themes': fm.get('themes', []),
                'relationships': fm.get('_parsed_rels', []),
            }
    return units


def build_graph(units: dict[str, dict]) -> tuple[dict, dict, dict]:
    """构建关系图：出度、入度、类型分布。"""
    outgoing = defaultdict(list)  # id -> [(target, type)]
    incoming = defaultdict(list)  # id -> [(source, type)]
    type_counts = Counter()

    for uid, info in units.items():
        for rel in info['relationships']:
            target = rel.get('target', '')
            rtype = rel.get('type', '?')
            if target:
                outgoing[uid].append((target, rtype))
                incoming[target].append((uid, rtype))
                type_counts[rtype] += 1

    return dict(outgoing), dict(incoming), dict(type_counts)


def find_structural_holes(units: dict[str, dict],
                          outgoing: dict, incoming: dict) -> list[dict]:
    """发现结构洞：共享相同主题但未连接的单元群。"""
    # 按主题分组
    theme_groups = defaultdict(list)
    for uid, info in units.items():
        for theme in info.get('themes', []):
            theme_groups[theme].append(uid)

    holes = []
    for theme, members in theme_groups.items():
        if len(members) < 2:
            continue
        # 检查主题组内是否有 CON 未连接到任何 OPI
        cons = [u for u in members if u.startswith('CON')]
        opis = [u for u in members if u.startswith('OPI')]
        if cons and not opis:
            holes.append({
                'theme': theme,
                'issue': f'主题"{theme}"有{len(cons)}个CON但无OPI',
                'units': cons,
            })
        # 检查是否有单元完全孤立于此主题组
        for u in members:
            neighbors = set(t for t, _ in outgoing.get(u, [])) | set(s for s, _ in incoming.get(u, []))
            overlap = neighbors & set(members)
            if not overlap and len(members) > 2:
                holes.append({
                    'theme': theme,
                    'issue': f'{u} 在主题"{theme}"中无同主题连接',
                    'units': [u],
                })

    return holes


def main():
    if len(sys.argv) < 2:
        print("用法: python relationship_analyzer.py <项目目录> [--json] [--csv]")
        sys.exit(1)

    project_dir = Path(sys.argv[1]).resolve()
    use_json = '--json' in sys.argv
    output_csv = '--csv' in sys.argv

    units = collect_all_units(project_dir)
    if not units:
        print("[FAIL] 未找到内容单元")
        sys.exit(1)

    outgoing, incoming, type_counts = build_graph(units)

    # 被引用 Top 20
    in_degree = {uid: len(rels) for uid, rels in incoming.items()}
    top_in = sorted(in_degree.items(), key=lambda x: -x[1])[:20]

    # 总关系数
    total_rels = sum(type_counts.values())

    if use_json:
        import json
        result = {
            'total_units': len(units),
            'total_relationships': total_rels,
            'avg_relationships': round(total_rels / len(units), 1) if units else 0,
            'type_distribution': dict(type_counts),
            'top_in_degree': [
                {'id': uid, 'degree': d, 'title': units[uid]['title'][:40]}
                for uid, d in top_in if d > 0
            ],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"=== 关系网络分析 ===\n")
        print(f"内容单元总数: {len(units)}")
        print(f"关系总数: {total_rels}")
        print(f"平均关系数/单元: {total_rels/len(units):.1f}" if units else "N/A")

        # 类型分布
        print(f"\n--- 关系类型分布 ---")
        for rtype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"  {rtype}: {count}")

        # 被引用 Top 20
        print(f"\n--- 网络中心 Top 20（被引用最多） ---")
        for rank, (uid, deg) in enumerate(top_in, 1):
            if deg > 0:
                info = units[uid]
                print(f"  {rank:2d}. {uid} (入度{deg}): {info['title'][:50]}")

        # 结构洞
        holes = find_structural_holes(units, outgoing, incoming)
        if holes:
            print(f"\n--- 结构洞分析 ({len(holes)}) ---")
            for h in holes[:10]:
                print(f"  [WARN] {h['issue']}")
        else:
            print(f"\n--- 结构洞 ---")
            print(f"  [OK] 无显著结构洞")

        # 对标鲁大魔库
        print(f"\n--- 对标鲁大魔库 ---")
        print(f"  鲁大魔库: 978 单元, 5559 关系, 平均 5.7/单元")
        print(f"  当前项目: {len(units)} 单元, {total_rels} 关系, "
              f"平均 {total_rels/len(units):.1f}/单元" if units else "N/A")

    # 输出关系索引 CSV
    if output_csv:
        csv_path = project_dir / '03-处理状态' / '关系索引.csv'
        rows = [['source_id', 'source_type', 'source_title', 'relation_type',
                  'target_id', 'target_type', 'target_title', 'note',
                  'source_file', 'target_file', 'status']]
        for uid, info in units.items():
            for rel in info['relationships']:
                target = rel.get('target', '')
                target_info = units.get(target, {})
                rows.append([
                    uid,
                    info['type'],
                    info['title'],
                    rel.get('type', '?'),
                    target,
                    target_info.get('type', ''),
                    target_info.get('title', ''),
                    rel.get('note', ''),
                    info['file'],
                    target_info.get('file', ''),
                    '有效' if target in units else '目标缺失',
                ])
        csv_content = '\n'.join(
            ','.join(escape_csv(str(c)) for c in row) for row in rows
        ) + '\n'
        csv_path.write_text(csv_content, encoding='utf-8')
        print(f"\n关系索引已输出: {csv_path}")


if __name__ == '__main__':
    main()
