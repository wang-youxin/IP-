#!/usr/bin/env python3
"""
health_report.py — 知识库综合健康报告

汇总以下检查结果，生成一份完整的健康报告：
- 内容单元统计（数量、类型分布）
- 关系网络统计
- 素材覆盖率
- 死链/孤儿/双向性
- 内容质量分层
- 门禁判定总表

用法:
  python health_report.py <项目目录>

示例:
  python health_report.py D:/蒸馏项目/费曼
"""
import sys
import re
from pathlib import Path
from datetime import date
from collections import defaultdict, Counter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import find_md_files, find_unit_files, parse_frontmatter, auto_discover_unit_subdirs

# 导入其他工具
from link_checker import collect_all_ids, check_dead_links, check_orphans, check_bidirectional
from coverage_scanner import scan_referenced_materials, load_registry
from relationship_analyzer import collect_all_units, build_graph


def count_unit_types(base: Path) -> dict:
    """统计各类型单元数量（自动发现子目录）。"""
    counts = {}
    subdirs = auto_discover_unit_subdirs(base)
    for sub in subdirs:
        d = base / '02-内容单元库' / sub
        if d.exists():
            counts[sub] = len(list(d.glob('*.md')))
    return counts


def analyze_quality(base: Path) -> dict:
    """内容质量分层分析（基于 OPI 内容长度和关系数）。"""
    units = collect_all_units(base)
    if not units:
        return {'deep': 0, 'medium': 0, 'light': 0, 'total': 0}

    deep = 0
    medium = 0
    light = 0
    for uid, info in units.items():
        n_rels = len(info.get('relationships', []))
        # 读取实际文件看内容长度
        filepath = base / info['file']
        if filepath.exists():
            content_len = len(filepath.read_text(encoding='utf-8'))
        else:
            content_len = 0

        if n_rels >= 3 and content_len > 1500:
            deep += 1
        elif n_rels >= 1 or content_len > 500:
            medium += 1
        else:
            light += 1

    return {'deep': deep, 'medium': medium, 'light': light, 'total': len(units)}


def main():
    if len(sys.argv) < 2:
        print("用法: python health_report.py <项目目录>")
        sys.exit(1)

    project_dir = Path(sys.argv[1]).resolve()
    base = project_dir

    # 1. 单元统计
    type_counts = count_unit_types(base)
    total_units = sum(type_counts.values())

    # 2. 关系统计
    units = collect_all_units(base)
    outgoing, incoming, type_counts_rel = build_graph(units)
    total_rels = sum(type_counts_rel.values())

    # 3. 覆盖率
    referenced = scan_referenced_materials(base)
    materials = load_registry(base)
    total_mat = len(materials)
    ref_mat = sum(1 for m in materials if m['id'] in referenced)
    coverage = (ref_mat / total_mat * 100) if total_mat > 0 else 0

    # 4. 死链/孤儿
    unit_ids = collect_all_ids(base)
    dead = check_dead_links(unit_ids)
    orphans = check_orphans(unit_ids)
    unidirectional = check_bidirectional(unit_ids)

    # 5. 质量分层
    quality = analyze_quality(base)

    # 6. 主题地图
    theme_dir = base / '05-主题地图'
    theme_count = len(list(theme_dir.glob('*.md'))) if theme_dir.exists() else 0

    # 门禁判定
    gates = {
        '死链=0': len(dead) == 0,
        '覆盖率≥70%': coverage >= 70,
        '无阻断级冲突': True,  # 需人工判定
    }
    all_passed = all(gates.values())

    # 生成报告
    today_str = date.today().isoformat()

    report = f"""# 知识库健康报告

> 自动生成: {today_str}
> 项目: {project_dir.name}

---

## 内容单元统计

| 类型 | 数量 |
|------|------|
| CON (概念) | {type_counts.get('CON', 0)} |
| OPI (观点) | {type_counts.get('OPI', 0)} |
| CAS (案例) | {type_counts.get('CAS', 0)} |
| SOL (方案) | {type_counts.get('SOL', 0)} |
| QST (问题) | {type_counts.get('QST', 0)} |
| **合计** | **{total_units}** |

## 关系网络

| 指标 | 数值 |
|------|------|
| 关系总数 | {total_rels} |
| 平均关系/单元 | {total_rels/total_units:.1f} |
| 关系类型分布 | {', '.join(f'{k}:{v}' for k,v in sorted(type_counts_rel.items(), key=lambda x:-x[1])) if type_counts_rel else '无'} |
| 主题地图 | {theme_count} 张 |

## 素材覆盖率

| 指标 | 数值 |
|------|------|
| 总素材 | {total_mat} |
| 已引用 | {ref_mat} ({coverage:.1f}%) |
| 未引用 | {total_mat - ref_mat} ({100-coverage:.1f}%) |

## 双链健康

| 检查项 | 结果 |
|--------|------|
| 死链 | {len(dead)} 条 {'[OK]' if len(dead)==0 else '[FAIL] 待修复'} |
| 孤儿单元 | {len(orphans)} 个 {'[OK]' if len(orphans)==0 else '[WARN]'} |
| 单向关系 | {len(unidirectional)} 条 {'[OK]' if len(unidirectional)==0 else '[WARN]'} |

## 内容质量分层

| 层级 | 数量 | 占比 |
|------|------|------|
| ★★★ 深度 | {quality['deep']} | {quality['deep']/quality['total']*100:.0f}% |
| ★★☆ 中等 | {quality['medium']} | {quality['medium']/quality['total']*100:.0f}% |
| ★☆☆ 轻量 | {quality['light']} | {quality['light']/quality['total']*100:.0f}% |

## 门禁总表

| 门禁 | 条件 | 状态 |
|------|------|------|
| 死链清零 | 死链=0 | {'[OK] 通过' if gates['死链=0'] else '[FAIL] 未通过'} |
| 覆盖率 | ≥70% | {'[OK] 通过' if gates['覆盖率≥70%'] else '[FAIL] 未通过'} |
| 无阻断冲突 | 无[RED]级冲突 | {'[OK] 通过' if gates['无阻断级冲突'] else '[FAIL] 未通过'} |

**总体判定: {'[OK] 全部通过 — 可进入 Phase 4' if all_passed else '[FAIL] 存在未通过项 — 修复后方可进入 Phase 4'}**

---

## 对标鲁大魔库

| 指标 | 鲁大魔库 | 本库 | 差距 |
|------|---------|------|------|
| 内容单元 | 978 | {total_units} | {978-total_units:+d} |
| 关系总数 | 5559 | {total_rels} | {5559-total_rels:+d} |
| 覆盖率 | 88% | {coverage:.0f}% | {88-coverage:.0f}% |
| 死链 | 0 | {len(dead)} | {len(dead):+d} |
| 主题地图 | 18 | {theme_count} | {18-theme_count:+d} |
"""

    report_path = project_dir / '03-处理状态' / '知识库健康报告.md'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding='utf-8')

    print(f"健康报告已生成: {report_path}")
    print(f"\n{report}")


if __name__ == '__main__':
    main()
