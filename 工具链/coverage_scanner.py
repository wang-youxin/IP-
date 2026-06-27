#!/usr/bin/env python3
"""
coverage_scanner.py — 素材覆盖率分析

扫描所有内容单元和主题地图中的 source_documents 引用，
统计哪些素材已被引用、哪些未引用，按类型/标签分析未覆盖素材。

用法:
  python coverage_scanner.py <项目目录> [--json]

示例:
  python coverage_scanner.py D:/蒸馏项目/费曼
"""
import sys
import re
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import find_md_files, find_unit_files, parse_frontmatter, escape_csv, auto_discover_unit_subdirs


def scan_referenced_materials(base: Path) -> set[str]:
    """扫描所有内容单元和主题地图，收集被引用的 SRC-ID。"""
    referenced = set()

    # 内容单元 — 自动发现子目录
    subdirs = auto_discover_unit_subdirs(base)
    for f in find_unit_files(base, subdirs):
        content = f.read_text(encoding='utf-8')
        fm = parse_frontmatter(content)
        for src in fm.get('source_documents', []):
            referenced.add(src.strip())
        # 也扫描正文中的 SRC-XX-XXX 引用
        refs = re.findall(r'SRC-[\w-]+', content)
        referenced.update(refs)

    # 主题地图
    theme_dir = base / '05-主题地图'
    if theme_dir.exists():
        for f in theme_dir.glob('*.md'):
            content = f.read_text(encoding='utf-8')
            refs = re.findall(r'SRC-[\w-]+', content)
            referenced.update(refs)

    return referenced


def load_registry(base: Path) -> list[dict]:
    """加载素材注册表。"""
    registry_path = base / '03-处理状态' / '来源注册表.csv'
    if not registry_path.exists():
        return []

    materials = []
    with open(registry_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    if len(lines) < 2:
        return []

    for line in lines[1:]:
        parts = _parse_csv_line(line)
        if len(parts) >= 6:
            materials.append({
                'id': parts[0].strip(),
                'path': parts[1].strip(),
                'type': parts[2].strip(),
                'status': parts[4].strip(),
            })
    return materials


def _parse_csv_line(line: str) -> list[str]:
    cells = []
    current = ""
    in_quotes = False
    for ch in line:
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ',' and not in_quotes:
            cells.append(current)
            current = ""
        else:
            current += ch
    cells.append(current)
    return cells


def main():
    if len(sys.argv) < 2:
        print("用法: python coverage_scanner.py <项目目录> [--json]")
        sys.exit(1)

    project_dir = Path(sys.argv[1]).resolve()
    use_json = '--json' in sys.argv

    referenced = scan_referenced_materials(project_dir)
    materials = load_registry(project_dir)

    total = len(materials)
    ref_count = sum(1 for m in materials if m['id'] in referenced)
    unref_count = total - ref_count

    # 未引用素材按类型分组
    unref_by_type = defaultdict(list)
    for m in materials:
        if m['id'] not in referenced:
            unref_by_type[m['type']].append(m)

    coverage_pct = (ref_count / total * 100) if total > 0 else 0

    if use_json:
        import json
        result = {
            'total_materials': total,
            'referenced': ref_count,
            'unreferenced': unref_count,
            'coverage_pct': round(coverage_pct, 1),
            'unreferenced_by_type': {
                t: [m['id'] for m in items]
                for t, items in sorted(unref_by_type.items())
            },
            'passed': coverage_pct >= 70,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"=== 素材覆盖率报告 ===\n")
        print(f"总素材数: {total}")
        print(f"已引用: {ref_count} ({coverage_pct:.1f}%)")
        print(f"未引用: {unref_count} ({100-coverage_pct:.1f}%)")

        # 按类型
        print(f"\n--- 未引用素材（按类型） ---")
        for stype, items in sorted(unref_by_type.items(), key=lambda x: -len(x[1])):
            print(f"  {stype}: {len(items)} 条")
            for m in items[:5]:
                print(f"    - {m['id']}: {m['path'][:60]}")
            if len(items) > 5:
                print(f"    ... 还有 {len(items)-5} 条")

        # 覆盖率评级
        print(f"\n--- 覆盖率评级 ---")
        if coverage_pct >= 88:
            print(f"[GREEN] 优秀 ({coverage_pct:.1f}%) — 达到鲁大魔库水平(88%)")
        elif coverage_pct >= 70:
            print(f"[GREEN] 合格 ({coverage_pct:.1f}%) — 满足门禁要求")
        elif coverage_pct >= 50:
            print(f"[YELLOW] 偏低 ({coverage_pct:.1f}%) — 诚实边界需说明")
        else:
            print(f"[RED] 不足 ({coverage_pct:.1f}%) — 蒸馏置信度受限")

        # 门禁
        print(f"\n=== 门禁判定 ===")
        if coverage_pct >= 70:
            print("[OK] 通过 — 覆盖率≥70%")
        else:
            print("[FAIL] 未通过 — 覆盖率<70%，需补充引用或诚实边界说明")


if __name__ == '__main__':
    main()
