#!/usr/bin/env python3
"""
cooccurrence_analyzer.py — 共现网络中心性分析器

实现 Phase -1.5 Head 2 (CO-W) 的共现网络中心性计算。
纯 Python 标准库，零外部依赖。

功能:
  1. 度中心性 (degree centrality)         — 关键词直接连接数
  2. 介数中心性 (betweenness centrality)  — 关键词作为"桥梁"的重要性
  3. 特征向量中心性 (eigenvector centrality) — 关键词与重要关键词的连接度
  4. 社区检测 (Louvain 算法)              — 自动发现概念群落

输入: 场景文档目录 + CON/OPI 列表（JSON）
输出: 共现矩阵(CSV) + 中心性排名(JSON) + 网络可视化数据(JSON)

用法:
  python cooccurrence_analyzer.py <项目目录> --keywords <关键词JSON> --scenes <场景目录>
  python cooccurrence_analyzer.py D:/蒸馏项目/费曼 --keywords keywords.json --json
"""
import sys
import json
import csv
from pathlib import Path
from collections import defaultdict
from itertools import combinations
from math import sqrt, log


sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import parse_frontmatter


# ══════════════════════════════════════════════════════
# 核心算法
# ══════════════════════════════════════════════════════

def build_cooccurrence_matrix(scene_docs: list[Path], keywords: list[str]) -> dict:
    """
    扫描所有场景文档，统计关键词在同一场景中的共现次数。

    返回:
      {
        "matrix": {kw1: {kw2: count, ...}, ...},
        "doc_freq": {kw: num_scenes},        # 每个关键词出现在多少个场景中
        "total_scenes": int,
        "cooccur_pairs": [(kw1, kw2, count)], # 排序后的共现对
      }
    """
    matrix = defaultdict(lambda: defaultdict(int))
    doc_freq = defaultdict(int)
    total_scenes = 0
    kw_set = set(k.lower() for k in keywords)

    for scene_file in scene_docs:
        content = scene_file.read_text(encoding='utf-8')
        # 从全文 + frontmatter keywords 中提取
        fm = parse_frontmatter(content)
        fm_keywords = [k.lower() for k in fm.get('keywords', [])]
        text_lower = content.lower()

        # 出现在此场景中的关键词
        present = set()
        for kw in kw_set:
            if kw in text_lower or kw in fm_keywords:
                present.add(kw)
                doc_freq[kw] += 1

        if present:
            total_scenes += 1
            for kw1, kw2 in combinations(sorted(present), 2):
                matrix[kw1][kw2] += 1
                matrix[kw2][kw1] += 1

    # 构建排序后的共现对列表
    pairs = []
    seen = set()
    for kw1 in matrix:
        for kw2, count in matrix[kw1].items():
            pair_key = tuple(sorted([kw1, kw2]))
            if pair_key not in seen:
                seen.add(pair_key)
                pairs.append((kw1, kw2, count))
    pairs.sort(key=lambda x: -x[2])

    return {
        'matrix': {k: dict(v) for k, v in matrix.items()},
        'doc_freq': dict(doc_freq),
        'total_scenes': total_scenes,
        'cooccur_pairs': pairs,
    }


def degree_centrality(kw: str, matrix: dict, doc_freq: dict, n_nodes: int) -> float:
    """度中心性：与该关键词共现的其他关键词数量（归一化）。"""
    if n_nodes <= 1:
        return 0.0
    return len(matrix.get(kw, {})) / (n_nodes - 1)


def betweenness_centrality(kw: str, matrix: dict, all_nodes: list[str]) -> float:
    """
    介数中心性（简化版）：该关键词在多少对关键词的最短路径上出现。
    对于共现网络，使用归一化后的"桥梁度"——如果A只通过kw连接到其他节点，
    kw的桥梁度就高。
    """
    neighbors = set(matrix.get(kw, {}).keys())
    if len(neighbors) < 2:
        return 0.0

    # 简化的介数中心性：kw 的邻居之间如果没有直接连接，kw 就是它们的桥梁
    bridge_count = 0
    neighbor_list = sorted(neighbors)
    for i, n1 in enumerate(neighbor_list):
        for n2 in neighbor_list[i+1:]:
            if n2 not in matrix.get(n1, {}):
                bridge_count += 1

    n = len(all_nodes)
    if n <= 2:
        return 0.0
    max_possible = (n - 1) * (n - 2) / 2
    return bridge_count / max_possible if max_possible > 0 else 0.0


def eigenvector_centrality(matrix: dict, all_nodes: list[str], iterations: int = 100) -> dict[str, float]:
    """
    特征向量中心性（幂迭代法）。
    一个节点的重要性取决于连接到它的节点的重要性。
    """
    n = len(all_nodes)
    if n == 0:
        return {}

    # 初始化
    scores = {node: 1.0 / n for node in all_nodes}

    for _ in range(iterations):
        new_scores = {}
        for node in all_nodes:
            new_scores[node] = sum(
                scores.get(neighbor, 0) * matrix.get(node, {}).get(neighbor, 0)
                for neighbor in matrix.get(node, {})
            )
        # 归一化
        norm = sqrt(sum(v * v for v in new_scores.values())) or 1.0
        for node in new_scores:
            new_scores[node] /= norm

        # 检查收敛
        max_diff = max(abs(new_scores[n] - scores[n]) for n in all_nodes)
        scores = new_scores
        if max_diff < 1e-6:
            break

    # 归一化到 [0, 1]
    max_score = max(scores.values()) or 1.0
    return {k: round(v / max_score, 4) for k, v in scores.items()}


def louvain_community_detection(matrix: dict, all_nodes: list[str]) -> dict[str, int]:
    """
    Louvain 社区检测算法的简化实现。

    阶段1: 每个节点初始为自己的社区，迭代移动节点到最大化模块度的社区。
    阶段2: 收敛或达到最大迭代次数。
    """
    if len(all_nodes) <= 1:
        return {n: 0 for n in all_nodes}

    # 初始化：每个节点自己的社区
    community = {node: i for i, node in enumerate(all_nodes)}

    # 计算总边权重
    total_weight = sum(
        matrix.get(n1, {}).get(n2, 0)
        for n1 in matrix for n2 in matrix[n1]
    ) / 2  # 每条边计了两次
    if total_weight == 0:
        return community

    n_nodes = len(all_nodes)
    # 节点度数
    degree = {
        node: sum(matrix.get(node, {}).values())
        for node in all_nodes
    }
    # 社区内部权重
    def comm_weight(node, comm, exclude_node=True):
        w = 0
        for other in all_nodes:
            if other == node and exclude_node:
                continue
            if community[other] == comm:
                w += matrix.get(node, {}).get(other, 0)
        return w

    max_iterations = 20
    for _ in range(max_iterations):
        moved = False
        for node in all_nodes:
            current_comm = community[node]
            ki = degree[node]

            # 评估移到每个邻居社区后的模块度变化
            neighbor_comms = set()
            for neighbor in matrix.get(node, {}):
                neighbor_comms.add(community[neighbor])
            neighbor_comms.add(current_comm)

            best_comm = current_comm
            best_delta_q = 0.0

            for target_comm in neighbor_comms:
                # Σin = 目标社区内部权重
                sigma_in = sum(
                    matrix.get(n1, {}).get(n2, 0)
                    for n1 in all_nodes if community[n1] == target_comm
                    for n2 in all_nodes if community[n2] == target_comm and n1 < n2
                )
                # Σtot = 目标社区所有节点的度数之和
                sigma_tot = sum(degree[n] for n in all_nodes if community[n] == target_comm)
                # ki,in = 节点与目标社区的连接权重
                ki_in = comm_weight(node, target_comm, exclude_node=False)

                if target_comm == current_comm:
                    # 移除当前节点的贡献
                    sigma_in_old = sigma_in
                    sigma_tot_old = sigma_tot

                    # 新社区（去掉节点）
                    sigma_in_new = sigma_in_old - 2 * ki_in
                    sigma_tot_new = sigma_tot_old - ki

                    delta_q_remove = (
                        (sigma_in_new / (2 * total_weight) - (sigma_tot_new / (2 * total_weight)) ** 2)
                        - (sigma_in_old / (2 * total_weight) - (sigma_tot_old / (2 * total_weight)) ** 2)
                    )

                    # 加入目标社区
                    sigma_in_target = sum(
                        matrix.get(n1, {}).get(n2, 0)
                        for n1 in all_nodes if community[n1] == target_comm
                        for n2 in all_nodes if community[n2] == target_comm and n1 < n2
                    )
                    sigma_tot_target = sum(degree[n] for n in all_nodes if community[n] == target_comm)

                    if target_comm != current_comm:
                        delta_q = (
                            (sigma_in_new / (2 * total_weight) - (sigma_tot_new / (2 * total_weight)) ** 2)
                            + ((sigma_in_target + ki_in) / (2 * total_weight)
                               - ((sigma_tot_target + ki) / (2 * total_weight)) ** 2)
                            - (sigma_in / (2 * total_weight) - (sigma_tot / (2 * total_weight)) ** 2)
                            - (sigma_in_target / (2 * total_weight) - (sigma_tot_target / (2 * total_weight)) ** 2)
                        )
                    else:
                        delta_q = delta_q_remove
                else:
                    sigma_in_old = sum(
                        matrix.get(n1, {}).get(n2, 0)
                        for n1 in all_nodes if community[n1] == current_comm
                        for n2 in all_nodes if community[n2] == current_comm and n1 < n2
                    )
                    sigma_tot_old = sum(degree[n] for n in all_nodes if community[n] == current_comm)
                    sigma_in_new = sigma_in_old - 2 * ki_in
                    sigma_tot_new = sigma_tot_old - ki
                    sigma_in_target = sum(
                        matrix.get(n1, {}).get(n2, 0)
                        for n1 in all_nodes if community[n1] == target_comm
                        for n2 in all_nodes if community[n2] == target_comm and n1 < n2
                    )
                    sigma_tot_target = sum(degree[n] for n in all_nodes if community[n] == target_comm)

                    delta_q = (
                        ((sigma_in_new + sigma_in_target + ki_in) / (2 * total_weight)
                         - ((sigma_tot_new + sigma_tot_target + ki) / (2 * total_weight)) ** 2)
                        - (sigma_in_old / (2 * total_weight) - (sigma_tot_old / (2 * total_weight)) ** 2)
                        - (sigma_in_target / (2 * total_weight) - (sigma_tot_target / (2 * total_weight)) ** 2)
                    )

                if delta_q > best_delta_q:
                    best_delta_q = delta_q
                    best_comm = target_comm

            if best_comm != current_comm:
                community[node] = best_comm
                moved = True

        if not moved:
            break

    # 重新编号社区为 0, 1, 2...
    unique_comms = sorted(set(community.values()))
    comm_map = {old: new for new, old in enumerate(unique_comms)}
    return {node: comm_map[c] for node, c in community.items()}


# ══════════════════════════════════════════════════════
# 综合评分
# ══════════════════════════════════════════════════════

def compute_comprehensive_scores(
    all_nodes: list[str],
    matrix: dict,
    doc_freq: dict,
    total_scenes: int,
) -> list[dict]:
    """
    计算每个关键词的综合中心性得分。

    综合得分 = 0.40 × 特征向量中心性 + 0.30 × 度中心性
             + 0.20 × 介数中心性 + 0.10 × 文档频率
    """
    n = len(all_nodes)
    if n == 0:
        return []

    dc = {kw: degree_centrality(kw, matrix, doc_freq, n) for kw in all_nodes}
    bc = {kw: betweenness_centrality(kw, matrix, all_nodes) for kw in all_nodes}
    ec = eigenvector_centrality(matrix, all_nodes)
    communities = louvain_community_detection(matrix, all_nodes)

    results = []
    for kw in all_nodes:
        df_norm = doc_freq.get(kw, 0) / max(total_scenes, 1)
        composite = round(
            0.40 * ec.get(kw, 0) + 0.30 * dc[kw] + 0.20 * bc[kw] + 0.10 * df_norm, 4
        )
        results.append({
            'keyword': kw,
            'degree_centrality': round(dc[kw], 4),
            'betweenness_centrality': round(bc[kw], 4),
            'eigenvector_centrality': ec.get(kw, 0),
            'document_frequency': doc_freq.get(kw, 0),
            'document_frequency_norm': round(df_norm, 4),
            'composite_score': composite,
            'community': communities.get(kw, -1),
        })
    results.sort(key=lambda x: -x['composite_score'])
    return results


# ══════════════════════════════════════════════════════
# 数据加载
# ══════════════════════════════════════════════════════

def load_scene_docs(project_dir: Path) -> list[Path]:
    """加载场景文档。优先加载 02-场景文档库/，回退到搜索 SCN-*.md。"""
    scene_dir = project_dir / '02-场景文档库'
    if scene_dir.exists():
        return sorted(scene_dir.rglob('SCN-*.md'))

    # 回退：搜索所有带场景 ID 的 md 文件
    scenes = []
    for pattern in ['02-场景文档库', '01-原始素材区', '.']:
        d = project_dir / pattern
        if d.exists():
            for f in d.rglob('*.md'):
                if f.stem.startswith('SCN-'):
                    scenes.append(f)
    return sorted(set(scenes))


def load_keywords(project_dir: Path, keywords_file: str = None) -> list[str]:
    """
    加载关键词列表。
    1. 如果指定了 JSON 文件，从中读取
    2. 否则从 02-内容单元库/ 的 CON frontmatter 中提取
    3. 回退到从场景文档 frontmatter 中提取
    """
    if keywords_file:
        kw_path = Path(keywords_file)
        if not kw_path.is_absolute():
            kw_path = project_dir / kw_path
        if kw_path.exists():
            data = json.loads(kw_path.read_text(encoding='utf-8'))
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return list(data.keys())

    # 从 CON 提取
    keywords = set()
    con_dir = project_dir / '02-内容单元库' / 'CON'
    if con_dir.exists():
        for f in con_dir.glob('*.md'):
            fm = parse_frontmatter(f.read_text(encoding='utf-8'))
            title = fm.get('title', '')
            if title:
                keywords.add(title)
            for kw in fm.get('keywords', []):
                keywords.add(kw)

    if keywords:
        return sorted(keywords)

    # 回退：从场景文档提取
    scenes = load_scene_docs(project_dir)
    for f in scenes:
        fm = parse_frontmatter(f.read_text(encoding='utf-8'))
        for kw in fm.get('keywords', []):
            keywords.add(kw)
    return sorted(keywords)


# ══════════════════════════════════════════════════════
# 主程序
# ══════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("用法: python cooccurrence_analyzer.py <项目目录> [选项]")
        print()
        print("选项:")
        print("  --keywords <文件>    关键词 JSON 文件路径")
        print("  --scenes <目录>      场景文档目录（默认 02-场景文档库/）")
        print("  --json               输出 JSON 格式")
        print("  --output <目录>      输出目录（默认项目目录）")
        print()
        print("示例:")
        print("  python cooccurrence_analyzer.py D:/蒸馏项目/费曼")
        print("  python cooccurrence_analyzer.py D:/蒸馏项目/费曼 --keywords my_keywords.json --json")
        sys.exit(1)

    project_dir = Path(sys.argv[1]).resolve()
    use_json = '--json' in sys.argv

    # 解析选项
    keywords_file = None
    for i, arg in enumerate(sys.argv):
        if arg == '--keywords' and i + 1 < len(sys.argv):
            keywords_file = sys.argv[i + 1]

    # 加载数据
    scenes = load_scene_docs(project_dir)
    keywords = load_keywords(project_dir, keywords_file)

    if not scenes:
        print("[FAIL] 未找到场景文档（SCN-*.md）。请先执行 Phase -1 语义切分。", file=sys.stderr)
        sys.exit(1)

    if not keywords:
        print("[FAIL] 未找到关键词。请先执行 Phase 1/2 概念提取，或使用 --keywords 指定。", file=sys.stderr)
        sys.exit(1)

    if not use_json:
        print(f"场景文档: {len(scenes)} 个")
        print(f"关键词: {len(keywords)} 个")
        print(f"分析中...")

    # 构建共现矩阵
    cooc = build_cooccurrence_matrix(scenes, keywords)
    matrix = cooc['matrix']
    all_nodes = sorted(matrix.keys())

    if len(all_nodes) < 2:
        print("[WARN] 共现关键词不足2个，无法做中心性分析。", file=sys.stderr)
        if use_json:
            print(json.dumps({'error': 'insufficient_nodes', 'node_count': len(all_nodes)}, ensure_ascii=False))
        sys.exit(0)

    # 计算中心性
    scores = compute_comprehensive_scores(all_nodes, matrix, cooc['doc_freq'], cooc['total_scenes'])
    communities = louvain_community_detection(matrix, all_nodes)

    if use_json:
        output = {
            'total_scenes': cooc['total_scenes'],
            'total_keywords': len(keywords),
            'active_nodes': len(all_nodes),
            'cooccurrence_pairs': [
                {'kw1': p[0], 'kw2': p[1], 'count': p[2]}
                for p in cooc['cooccur_pairs'][:100]  # Top 100
            ],
            'centrality_ranking': scores,
            'community_count': len(set(communities.values())),
            'communities': {k: v for k, v in sorted(communities.items(), key=lambda x: x[1])},
            'network_visualization': {
                'nodes': [{'id': s['keyword'], 'score': s['composite_score'], 'community': s['community']} for s in scores],
                'edges': [
                    {'source': p[0], 'target': p[1], 'weight': p[2]}
                    for p in cooc['cooccur_pairs'][:200]
                ],
            },
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"\n=== 共现网络分析报告 ===\n")
        print(f"场景文档: {cooc['total_scenes']} 个")
        print(f"活跃关键词: {len(all_nodes)} / {len(keywords)} 个")
        print(f"共现对: {len(cooc['cooccur_pairs'])} 对")
        print(f"社区数: {len(set(communities.values()))} 个")

        print(f"\n--- 中心性 Top 20 ---")
        print(f"{'排名':<5} {'关键词':<25} {'综合':>8} {'度中心':>8} {'介数':>8} {'特征向量':>8} {'文档频率':>8} {'社区':>5}")
        print("-" * 85)
        for i, s in enumerate(scores[:20], 1):
            print(f"{i:<5} {s['keyword']:<25} {s['composite_score']:>8.4f} {s['degree_centrality']:>8.4f} "
                  f"{s['betweenness_centrality']:>8.4f} {s['eigenvector_centrality']:>8.4f} "
                  f"{s['document_frequency_norm']:>8.4f} {s['community']:>5}")

        print(f"\n--- 共现对 Top 20 ---")
        for i, (kw1, kw2, count) in enumerate(cooc['cooccur_pairs'][:20], 1):
            print(f"  {i:>2}. {kw1} ←→ {kw2}  ({count}次)")

        print(f"\n--- 社区分布 ---")
        comm_groups = defaultdict(list)
        for node, comm in communities.items():
            comm_groups[comm].append(node)
        for comm, members in sorted(comm_groups.items()):
            print(f"  社区 {comm} ({len(members)}个): {', '.join(members[:10])}{'...' if len(members) > 10 else ''}")

        # 输出 CSV
        csv_path = project_dir / '03-处理状态' / 'cooccurrence_matrix.csv'
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['keyword1', 'keyword2', 'count'])
            for kw1, kw2, count in cooc['cooccur_pairs']:
                writer.writerow([kw1, kw2, count])
        print(f"\n[OK] 共现矩阵已保存: {csv_path}")

        # 输出 JSON
        json_path = project_dir / '03-处理状态' / 'centrality_ranking.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({
                'centrality': scores,
                'communities': {k: v for k, v in sorted(communities.items())},
                'network': {
                    'nodes': [{'id': s['keyword'], 'score': s['composite_score'], 'community': s['community']} for s in scores],
                    'edges': [{'source': p[0], 'target': p[1], 'weight': p[2]} for p in cooc['cooccur_pairs'][:200]],
                },
            }, f, ensure_ascii=False, indent=2)
        print(f"[OK] 中心性排名已保存: {json_path}")

        # 隐藏概念（高频共现但非原始关键词的词对——这里简化为高介数中心性的连接）
        print(f"\n--- 隐藏概念（高桥梁度关键词） ---")
        high_bridge = sorted(scores, key=lambda x: -x['betweenness_centrality'])[:5]
        for s in high_bridge:
            if s['betweenness_centrality'] > 0.05:
                print(f"  🔍 {s['keyword']} — 连接了不同的概念群落（介数={s['betweenness_centrality']:.4f}）")


if __name__ == '__main__':
    main()
