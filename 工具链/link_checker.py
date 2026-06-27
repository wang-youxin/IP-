#!/usr/bin/env python3
"""
link_checker.py — 死链/孤儿/双向性 全量检查

扫描 02-内容单元库/ 和 05-主题地图/ 中的所有 [[链接]] 和 relationships，
检测死链、孤儿单元、单向关系。

用法:
  python link_checker.py <项目目录> [--json] [--fix]

选项:
  --json  输出 JSON 格式
  --fix   自动标记问题（不实际修改文件，仅输出修复建议）

示例:
  python link_checker.py D:/蒸馏项目/费曼
"""
import sys
import re
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import find_md_files, find_unit_files, parse_frontmatter, extract_wiki_links, auto_discover_unit_subdirs


def collect_all_ids(base: Path) -> dict[str, dict]:
    """收集所有内容单元 + 素材文件的 ID 和元数据。"""
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
                'relationships': fm.get('_parsed_rels', []),
                'wiki_links': extract_wiki_links(content),
            }

    # 同时扫描原始素材区，避免 LD-XXX/SRC-XXX 被误报为死链
    source_dirs = [
        base / '01-原始素材区',
        base / '01-原始素材区' / '完整副本',
        base / '01-原始素材区' / '完整副本' / '对话',
    ]
    for sd in source_dirs:
        if sd.exists():
            for f in sd.rglob('*.md'):
                stem = f.stem
                # 提取可能的 ID（如 LD-001, SRC-FM-001）
                uid_match = re.match(r'^(LD-\d+|SRC-[\w-]+)', stem)
                if uid_match:
                    uid = uid_match.group(1)
                    if uid not in units:
                        units[uid] = {
                            'file': str(f.relative_to(base)),
                            'type': '素材',
                            'title': stem,
                            'relationships': [],
                            'wiki_links': [],
                        }

    return units


def check_dead_links(units: dict[str, dict]) -> list[dict]:
    """检查死链：[[链接]] 指向不存在的 ID。"""
    all_ids = set(units.keys())
    dead = []
    for uid, info in units.items():
        # 检查 wikilinks
        for link in info['wiki_links']:
            # 跳过非 ID 格式的链接（如路径链接）
            if not re.match(r'^[A-Z]+-\d+', link):
                continue
            base_id = link.split('_')[0] if '_' in link else link
            if base_id not in all_ids and link not in all_ids:
                dead.append({
                    'source': uid,
                    'source_file': info['file'],
                    'target': link,
                    'type': 'wikilink',
                })
        # 检查 relationships
        for rel in info['relationships']:
            target = rel.get('target', '')
            if target and target not in all_ids:
                dead.append({
                    'source': uid,
                    'source_file': info['file'],
                    'target': target,
                    'type': f"relationship({rel.get('type', '?')})",
                })
    return dead


def check_orphans(units: dict[str, dict]) -> list[str]:
    """检查孤儿单元：没有被任何其他单元引用。"""
    # 构建被引用集合（从 wikilinks + relationships + path-based links）
    referenced = set()
    # 建立 ID→file 映射，用于路径链接反向查找
    id_to_file = {uid: info['file'] for uid, info in units.items()}

    for uid, info in units.items():
        for link in info['wiki_links']:
            # 直接 ID
            base_id = link.split('_')[0] if '_' in link else link
            referenced.add(base_id)
            referenced.add(link)
            # 路径引用：从文件路径提取 ID
            filename = Path(link).stem
            id_match = re.match(r'^([A-Z]+-\d+)', filename)
            if id_match:
                referenced.add(id_match.group(1))
        for rel in info['relationships']:
            t = rel.get('target', '')
            if t:
                # relationship targets can be bare IDs or ID_title format
                base = t.split('_')[0] if '_' in t else t
                referenced.add(t)
                referenced.add(base)

    orphans = []
    for uid in units:
        if uid not in referenced and not uid.startswith('LD-') and not uid.startswith('SRC-'):
            orphans.append(uid)
    return orphans


def check_bidirectional(units: dict[str, dict]) -> list[dict]:
    """检查单向关系：A 声明了与 B 的关系但 B 没有反向声明。"""
    # 建立关系图
    rel_graph = defaultdict(set)  # A -> {B, C}
    for uid, info in units.items():
        for rel in info['relationships']:
            target = rel.get('target', '')
            if target and target in units:
                rel_graph[uid].add(target)

    unidirectional = []
    for source, targets in rel_graph.items():
        for target in targets:
            if source not in rel_graph.get(target, set()):
                unidirectional.append({
                    'source': source,
                    'target': target,
                    'note': f'{source} → {target} 存在，但 {target} → {source} 不存在',
                })
    return unidirectional


def main():
    if len(sys.argv) < 2:
        print("用法: python link_checker.py <项目目录> [--json]")
        sys.exit(1)

    project_dir = Path(sys.argv[1]).resolve()
    use_json = '--json' in sys.argv

    base = project_dir
    units = collect_all_ids(base)

    if not units:
        print("[FAIL] 未找到内容单元。请先创建 CON/OPI/CAS/SOL/QST 文件。")
        sys.exit(1)

    dead = check_dead_links(units)
    orphans = check_orphans(units)
    unidirectional = check_bidirectional(units)

    if use_json:
        import json
        result = {
            'total_units': len(units),
            'dead_links': len(dead),
            'dead_details': dead,
            'orphans': len(orphans),
            'orphan_ids': orphans,
            'unidirectional': len(unidirectional),
            'unidirectional_details': unidirectional[:50],
            'passed': len(dead) == 0 and len(unidirectional) == 0,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"=== 双链检查报告 ===\n")
        print(f"内容单元总数: {len(units)}")

        # ID 列表
        print(f"\n--- 已注册 ID ---")
        for uid in sorted(units.keys()):
            info = units[uid]
            print(f"  {uid}: {info['title'][:40]} ({info['type']})")

        # 死链
        print(f"\n--- 死链 ({len(dead)}) ---")
        if dead:
            for d in dead:
                print(f"  [FAIL] {d['source']} ({d['source_file']})")
                print(f"     → {d['target']} [{d['type']}] — 目标不存在")
        else:
            print("  [OK] 0 死链")

        # 孤儿
        print(f"\n--- 孤儿单元 ({len(orphans)}) ---")
        if orphans:
            for o in orphans:
                info = units[o]
                print(f"  [WARN] {o}: {info['title'][:50]} — 未被任何单元引用")
        else:
            print("  [OK] 0 孤儿")

        # 单向关系
        print(f"\n--- 单向关系 ({len(unidirectional)}) ---")
        if unidirectional:
            for u in unidirectional[:30]:
                print(f"  [WARN] {u['source']} → {u['target']}")
                print(f"     {u['note']}")
        else:
            print("  [OK] 全部双向闭合")

        # 门禁判定
        passed = len(dead) == 0
        print(f"\n=== 门禁判定 ===")
        if passed:
            print("[OK] 通过 — 死链=0，可进入 Phase 4")
        else:
            print(f"[FAIL] 未通过 — {len(dead)} 条死链待修复")


if __name__ == '__main__':
    main()
