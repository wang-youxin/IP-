#!/usr/bin/env python3
"""
pattern_emergence.py — 无监督跨场景模式涌现检测器

不预设行为标签，通过滑动窗口+N-gram+TF-IDF+层次聚类，从场景文档中
自动发现跨场景重复出现的模式簇，供人工命名。

与 cross_scene_detector.py 的区别:
  - cross_scene_detector: 验证你预设的15种行为模式是否跨场景显著
  - pattern_emergence: 不预设任何模式，从数据中无监督涌现

算法流程:
  1. 滑动窗口 — 在每个场景文档中滑动提取 N-gram（2-6字）
  2. TF-IDF — 计算每个 N-gram 的跨场景重要性
  3. 特征向量 — 每个 N-gram 表示为 [场景出现向量 + TF-IDF + 位置分布]
  4. 层次聚类 — 自底向上聚合，发现重复模式簇
  5. 输出 — 模式簇+每簇示例+环境分布，供人工命名

纯 Python 标准库，零外部依赖。

用法:
  python pattern_emergence.py <项目目录> [选项]
  python pattern_emergence.py D:/蒸馏项目/费曼 --min-scenes 3 --cluster-threshold 0.4 --json
"""
import sys
import json
import re
from pathlib import Path
from collections import defaultdict, Counter
from math import log, sqrt


sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import parse_frontmatter


# ══════════════════════════════════════════════════════
# 滑动窗口 N-gram 提取
# ══════════════════════════════════════════════════════

# 无意义停用词，过滤掉
STOP_NGRAMS = {
    '这个是', '那个是', '就是说', '然后呢', '对吧', '是不是',
    '有没有', '能不能', '什么的', '这样子', '就是说啊', '这个',
    '那个', '就是', '然后', '所以', '但是', '因为', '如果',
    '可以', '应该', '需要', '已经', '没有', '不是', '还是',
    '而且', '或者', '不过', '只是', '真的', '觉得', '知道',
    '可能', '比较', '特别', '非常', '一点', '一些', '很多',
}


def sliding_ngrams(text: str, n_min: int = 2, n_max: int = 6, step: int = 1) -> list[dict]:
    """
    滑动窗口提取 N-gram。

    返回:
      [{
        'ngram': '价值交换',
        'n': 4,
        'position': 0.35,   # 在文档中的相对位置
        'context': '...',    # 前后20字上下文
      }, ...]
    """
    # 清理文本：保留中文字符和标点
    cleaned = re.sub(r'[^一-鿿，。！？；：、""''（）]', '', text)
    if len(cleaned) < n_min:
        return []

    results = []
    for n in range(n_min, n_max + 1):
        for i in range(0, len(cleaned) - n + 1, step):
            ngram = cleaned[i:i + n]
            if ngram in STOP_NGRAMS:
                continue
            # 过滤纯标点或单字重复
            if len(set(ngram)) == 1:
                continue

            ctx_start = max(0, i - 10)
            ctx_end = min(len(cleaned), i + n + 10)
            results.append({
                'ngram': ngram,
                'n': n,
                'position': i / max(len(cleaned), 1),
                'context': cleaned[ctx_start:ctx_end],
            })

    return results


# ══════════════════════════════════════════════════════
# TF-IDF 计算
# ══════════════════════════════════════════════════════

def compute_tfidf(scene_ngrams: dict[str, list[dict]], total_scenes: int) -> dict[str, dict]:
    """
    计算每个 N-gram 的 TF-IDF。

    scene_ngrams: {scene_id: [ngram_dicts, ...]}

    返回:
      {ngram: {
        'tf': 0.123,           # 在所有场景中的平均词频
        'df': 5,               # 出现在多少个场景中
        'idf': 1.23,           # 逆文档频率
        'tfidf': 0.15,         # TF-IDF 分数
        'scene_count': 5,
        'total_occurrences': 23,
      }}
    """
    # 总 N-gram 数（用于 TF）
    total_ngrams_per_scene = {}
    for sid, ngrams in scene_ngrams.items():
        total_ngrams_per_scene[sid] = len(ngrams)

    # 文档频率
    doc_freq = defaultdict(int)
    ngram_occurrences = defaultdict(int)
    for sid, ngrams in scene_ngrams.items():
        seen = set()
        for ng in ngrams:
            ngram_occurrences[ng['ngram']] += 1
            if ng['ngram'] not in seen:
                doc_freq[ng['ngram']] += 1
                seen.add(ng['ngram'])

    # TF-IDF
    results = {}
    for ngram, df in doc_freq.items():
        # 平均 TF
        tf_sum = 0
        for sid, ngrams in scene_ngrams.items():
            count = sum(1 for ng in ngrams if ng['ngram'] == ngram)
            if total_ngrams_per_scene[sid] > 0:
                tf_sum += count / total_ngrams_per_scene[sid]
        avg_tf = tf_sum / max(total_scenes, 1)

        # IDF
        idf = log((total_scenes + 1) / (df + 1)) + 1

        results[ngram] = {
            'tf': round(avg_tf, 6),
            'df': df,
            'idf': round(idf, 4),
            'tfidf': round(avg_tf * idf, 6),
            'scene_count': df,
            'total_occurrences': ngram_occurrences[ngram],
        }

    return results


# ══════════════════════════════════════════════════════
# 特征向量构建
# ══════════════════════════════════════════════════════

def build_feature_vectors(
    tfidf_data: dict[str, dict],
    scene_ngrams: dict[str, list[dict]],
    min_scenes: int = 3,
) -> dict[str, dict]:
    """
    为每个满足最小场景要求的 N-gram 构建特征向量。

    特征:
      - scene_vector: [0/1 per scene] 在哪些场景出现
      - tfidf: TF-IDF 分数
      - position_mean: 平均位置
      - position_std: 位置标准差（跨场景分散度）
      - env_distribution: 环境分布
    """
    all_scenes = sorted(scene_ngrams.keys())
    scene_index = {s: i for i, s in enumerate(all_scenes)}
    total_scenes = len(all_scenes)

    vectors = {}
    for ngram, data in tfidf_data.items():
        if data['scene_count'] < min_scenes:
            continue

        # 场景向量
        scene_vector = [0] * total_scenes
        positions = []
        env_counter = defaultdict(Counter)

        for sid, ngrams in scene_ngrams.items():
            si = scene_index.get(sid)
            if si is None:
                continue
            for ng in ngrams:
                if ng['ngram'] == ngram:
                    scene_vector[si] = 1
                    positions.append(ng['position'])

        if not positions:
            continue

        # 位置统计
        pos_mean = sum(positions) / len(positions)
        pos_var = sum((p - pos_mean) ** 2 for p in positions) / len(positions)
        pos_std = sqrt(pos_var)

        vectors[ngram] = {
            'ngram': ngram,
            'scene_vector': scene_vector,
            'tfidf': data['tfidf'],
            'scene_count': data['scene_count'],
            'total_occurrences': data['total_occurrences'],
            'position_mean': round(pos_mean, 4),
            'position_std': round(pos_std, 4),
        }

    return vectors


# ══════════════════════════════════════════════════════
# 层次聚类（自底向上聚合）
# ══════════════════════════════════════════════════════

def cosine_similarity(v1: list[int], v2: list[int]) -> float:
    """两个场景向量的余弦相似度。"""
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = sqrt(sum(a * a for a in v1))
    norm2 = sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def hierarchical_clustering(
    vectors: dict[str, dict],
    similarity_threshold: float = 0.4,
) -> list[dict]:
    """
    自底向上层次聚类（平均链接）。

    两两合并最相似的簇，直到没有簇的相似度超过阈值。
    """
    ngrams = list(vectors.keys())
    if len(ngrams) < 2:
        return [{
            'cluster_id': 0,
            'ngrams': ngrams,
            'size': len(ngrams),
            'avg_similarity': 1.0,
            'examples': [vectors[n]['ngram'] for n in ngrams],
        }] if ngrams else []

    # 初始化：每个 N-gram 一个簇
    clusters = {
        i: {
            'id': i,
            'members': [ng],
            'scene_vectors': [vectors[ng]['scene_vector']],
        }
        for i, ng in enumerate(ngrams)
    }

    # 计算初始相似度矩阵
    n = len(ngrams)
    sim_matrix = {}
    for i in range(n):
        for j in range(i + 1, n):
            sim = cosine_similarity(
                vectors[ngrams[i]]['scene_vector'],
                vectors[ngrams[j]]['scene_vector'],
            )
            sim_matrix[(i, j)] = sim

    # 自底向上合并
    active = set(range(n))
    next_id = n

    while len(active) > 1:
        # 找最相似的簇对
        best_sim = -1
        best_pair = None
        for (i, j), sim in sim_matrix.items():
            if i in active and j in active and sim > best_sim:
                best_sim = sim
                best_pair = (i, j)

        if best_pair is None or best_sim < similarity_threshold:
            break

        # 合并
        a, b = best_pair
        merged_members = clusters[a]['members'] + clusters[b]['members']
        merged_vectors = clusters[a]['scene_vectors'] + clusters[b]['scene_vectors']

        clusters[next_id] = {
            'id': next_id,
            'members': merged_members,
            'scene_vectors': merged_vectors,
        }

        active.discard(a)
        active.discard(b)
        active.add(next_id)

        # 更新相似度（平均链接）
        for other in active:
            if other == next_id:
                continue
            other_members = clusters[other]['members']
            total_sim = 0.0
            count = 0
            for m1 in merged_members:
                for m2 in other_members:
                    i1 = ngrams.index(m1)
                    i2 = ngrams.index(m2)
                    key = (min(i1, i2), max(i1, i2))
                    if key in sim_matrix:
                        total_sim += sim_matrix[key]
                        count += 1
            if count > 0:
                sim_matrix[(min(next_id, other), max(next_id, other))] = total_sim / count

        next_id += 1

    # 收集最终簇
    result = []
    for cid in sorted(active):
        members = clusters[cid]['members']
        scene_vecs = clusters[cid]['scene_vectors']

        # 簇内平均相似度
        avg_sim = 1.0
        if len(members) > 1:
            sims = []
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    s = cosine_similarity(
                        vectors[members[i]]['scene_vector'],
                        vectors[members[j]]['scene_vector'],
                    )
                    sims.append(s)
            avg_sim = sum(sims) / len(sims) if sims else 1.0

        # 聚合统计
        scenes_set = set()
        total_occ = 0
        for m in members:
            total_occ += vectors[m]['total_occurrences']
            for si, val in enumerate(vectors[m]['scene_vector']):
                if val:
                    scenes_set.add(si)

        result.append({
            'cluster_id': cid,
            'ngrams': sorted(members, key=lambda x: vectors[x]['tfidf'], reverse=True),
            'size': len(members),
            'scene_count': len(scenes_set),
            'total_occurrences': total_occ,
            'avg_similarity': round(avg_sim, 4),
            'top_ngrams': sorted(members, key=lambda x: vectors[x]['tfidf'], reverse=True)[:8],
        })

    result.sort(key=lambda x: -x['size'])
    return result


# ══════════════════════════════════════════════════════
# 环境分布分析
# ══════════════════════════════════════════════════════

ENV_DIMS = ['physical', 'social', 'emotional', 'trigger', 'pressure', 'role']


def compute_cluster_env_distribution(
    cluster_ngrams: list[str],
    scene_ngrams: dict[str, list[dict]],
    scene_envs: dict[str, dict],
) -> dict:
    """计算一个模式簇的环境分布。"""
    env_counter = {dim: Counter() for dim in ENV_DIMS}
    scene_counter = Counter()

    for sid, ngrams in scene_ngrams.items():
        for ng in ngrams:
            if ng['ngram'] in cluster_ngrams:
                scene_counter[sid] += 1

    for sid in scene_counter:
        env = scene_envs.get(sid, {})
        for dim in ENV_DIMS:
            val = env.get(dim, '未知')
            env_counter[dim][val] += 1

    return {
        dim: dict(env_counter[dim].most_common(3))
        for dim in ENV_DIMS
    }


# ══════════════════════════════════════════════════════
# 文本清理与分割
# ══════════════════════════════════════════════════════

def load_scene_docs(project_dir: Path) -> list[Path]:
    """加载所有场景文档。"""
    scene_dir = project_dir / '02-场景文档库'
    if scene_dir.exists():
        return sorted(scene_dir.rglob('SCN-*.md'))

    scenes = []
    for pattern in ['02-场景文档库', '01-原始素材区']:
        d = project_dir / pattern
        if d.exists():
            for f in d.rglob('SCN-*.md'):
                scenes.append(f)
    return sorted(set(scenes))


# ══════════════════════════════════════════════════════
# 主程序
# ══════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("用法: python pattern_emergence.py <项目目录> [选项]")
        print()
        print("选项:")
        print("  --min-scenes <N>         最少跨场景出现次数（默认 3）")
        print("  --cluster-threshold <F>   聚类相似度阈值 0-1（默认 0.4，越低越多簇）")
        print("  --n-min <N>              最小 N-gram 长度（默认 2）")
        print("  --n-max <N>              最大 N-gram 长度（默认 6）")
        print("  --json                   输出 JSON 格式")
        print()
        print("示例:")
        print("  python pattern_emergence.py D:/蒸馏项目/费曼")
        print("  python pattern_emergence.py D:/蒸馏项目/费曼 --min-scenes 5 --cluster-threshold 0.3 --json")
        sys.exit(1)

    project_dir = Path(sys.argv[1]).resolve()
    use_json = '--json' in sys.argv

    # 解析参数
    min_scenes = 3
    cluster_threshold = 0.4
    n_min = 2
    n_max = 6
    for i, arg in enumerate(sys.argv):
        if arg == '--min-scenes' and i + 1 < len(sys.argv):
            try:
                min_scenes = int(sys.argv[i + 1])
            except ValueError:
                pass
        elif arg == '--cluster-threshold' and i + 1 < len(sys.argv):
            try:
                cluster_threshold = float(sys.argv[i + 1])
            except ValueError:
                pass
        elif arg == '--n-min' and i + 1 < len(sys.argv):
            try:
                n_min = int(sys.argv[i + 1])
            except ValueError:
                pass
        elif arg == '--n-max' and i + 1 < len(sys.argv):
            try:
                n_max = int(sys.argv[i + 1])
            except ValueError:
                pass

    # 加载场景文档
    scene_files = load_scene_docs(project_dir)
    if not scene_files:
        print("[FAIL] 未找到场景文档（SCN-*.md）。请先执行 Phase -1 语义切分。", file=sys.stderr)
        sys.exit(1)

    if not use_json:
        print(f"场景文档: {len(scene_files)} 个")
        print(f"N-gram 范围: {n_min}-{n_max} 字")
        print(f"最少场景: {min_scenes} | 聚类阈值: {cluster_threshold}")
        print(f"提取中...")

    # 提取 N-gram
    scene_ngrams = {}
    scene_envs = {}
    for sf in scene_files:
        content = sf.read_text(encoding='utf-8')
        fm = parse_frontmatter(content)
        scene_id = fm.get('id', sf.stem)

        # 提取环境标签
        env = {}
        for dim in ENV_DIMS:
            key = f'env_{dim}'
            env[dim] = fm.get(key, '未知')
        scene_envs[scene_id] = env

        # 去掉 frontmatter
        body = re.sub(r'^---.*?---', '', content, flags=re.DOTALL)
        ngrams = sliding_ngrams(body, n_min=n_min, n_max=n_max)
        scene_ngrams[scene_id] = ngrams

    total_ngrams = sum(len(v) for v in scene_ngrams.values())
    unique_ngrams = len(set(
        ng['ngram'] for ngrams in scene_ngrams.values() for ng in ngrams
    ))

    if not use_json:
        print(f"提取 N-gram: {total_ngrams} 个（去重后 {unique_ngrams} 个）")

    if total_ngrams == 0:
        print("[FAIL] 未提取到任何 N-gram。检查场景文档是否有足够的中文内容。", file=sys.stderr)
        sys.exit(1)

    # TF-IDF
    tfidf_data = compute_tfidf(scene_ngrams, len(scene_files))
    if not use_json:
        qualifying = sum(1 for d in tfidf_data.values() if d['scene_count'] >= min_scenes)
        print(f"TF-IDF 计算完成。≥{min_scenes}场景: {qualifying} 个 N-gram")

    # 特征向量
    vectors = build_feature_vectors(tfidf_data, scene_ngrams, min_scenes=min_scenes)
    if not use_json:
        print(f"特征向量: {len(vectors)} 个")

    if len(vectors) < 2:
        print(f"[WARN] 特征向量不足（{len(vectors)} 个），无法聚类。请降低 --min-scenes。", file=sys.stderr)
        if use_json:
            print(json.dumps({'clusters': [], 'warning': 'insufficient_vectors'}, ensure_ascii=False))
        sys.exit(0)

    # 层次聚类
    clusters = hierarchical_clustering(vectors, similarity_threshold=cluster_threshold)

    if not use_json:
        print(f"发现模式簇: {len(clusters)} 个")

    # 为每个簇计算环境分布和示例
    enriched_clusters = []
    for cl in clusters:
        env_dist = compute_cluster_env_distribution(
            cl['ngrams'], scene_ngrams, scene_envs
        )

        # 收集出现在的场景列表
        scenes_set = set()
        for ng_name in cl['ngrams']:
            for sid, ngrams in scene_ngrams.items():
                for ng in ngrams:
                    if ng['ngram'] == ng_name:
                        scenes_set.add(sid)

        # 取前5个场景的示例
        examples = []
        for sid in sorted(scenes_set)[:5]:
            context_samples = []
            for ng in scene_ngrams.get(sid, []):
                if ng['ngram'] in cl['top_ngrams'][:3]:
                    context_samples.append({
                        'ngram': ng['ngram'],
                        'context': ng['context'],
                    })
            if context_samples:
                examples.append({
                    'scene_id': sid,
                    'samples': context_samples[:2],
                })

        enriched_clusters.append({
            'cluster_id': cl['cluster_id'],
            'size': cl['size'],
            'scene_count': cl['scene_count'],
            'total_occurrences': cl['total_occurrences'],
            'avg_similarity': cl['avg_similarity'],
            'top_ngrams': cl['top_ngrams'],
            'env_distribution': env_dist,
            'examples': examples,
            # 建议标签（基于最高 TF-IDF N-gram 中最长的那个）
            'suggested_label': max(cl['top_ngrams'][:3], key=len) if cl['top_ngrams'] else '',
        })

    if use_json:
        output = {
            'total_scenes': len(scene_files),
            'total_ngrams': total_ngrams,
            'unique_ngrams': unique_ngrams,
            'qualifying_ngrams': len(vectors),
            'n_range': [n_min, n_max],
            'min_scenes': min_scenes,
            'cluster_threshold': cluster_threshold,
            'cluster_count': len(enriched_clusters),
            'clusters': enriched_clusters,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"\n=== 无监督模式涌现报告 ===\n")
        print(f"场景总数: {len(scene_files)}")
        print(f"N-gram 范围: {n_min}-{n_max} 字")
        print(f"提取 N-gram: {total_ngrams} 个（去重 {unique_ngrams} 个）")
        print(f"≥{min_scenes}场景的 N-gram: {len(vectors)} 个")
        print(f"发现模式簇: {len(enriched_clusters)} 个（相似度阈值={cluster_threshold}）")

        print(f"\n--- 涌现模式簇 ---")
        for i, cl in enumerate(enriched_clusters, 1):
            sim_bar = '█' * min(10, int(cl['avg_similarity'] * 10))
            print(f"\n{i}. [簇{cl['cluster_id']}] 规模={cl['size']} | "
                  f"跨{cl['scene_count']}场景 | "
                  f"簇内相似度={cl['avg_similarity']:.2f} {sim_bar}")
            print(f"   Top N-grams: {', '.join(cl['top_ngrams'][:5])}")
            print(f"   建议标签: 「{cl['suggested_label']}」")
            print(f"   总出现: {cl['total_occurrences']} 次")

            # 环境分布
            env_summary = []
            for dim in ENV_DIMS:
                if dim in cl['env_distribution'] and cl['env_distribution'][dim]:
                    top_val = list(cl['env_distribution'][dim].keys())[0]
                    env_summary.append(f"{dim}={top_val}")
            print(f"   环境: {', '.join(env_summary)}")

            # 示例
            if cl['examples']:
                ex = cl['examples'][0]
                if ex['samples']:
                    print(f"   示例: [{ex['scene_id']}] \"...{ex['samples'][0]['context']}...\"")

        print(f"\n--- 使用说明 ---")
        print(f"以上模式簇是通过无监督聚类自动发现的。")
        print(f"请为每个簇指定一个有意义的行为标签（如「反问模式」「压缩本质」「价值判断」）。")
        print(f"命名后，这些模式可作为 Phase 2 涌现维度发现的候选输入。")

        # 保存结果
        out_path = project_dir / '03-处理状态' / 'emergent_patterns.json'
        out_path.parent.mkdir(parents=True, exist_ok=True)
        save_data = {
            'parameters': {
                'n_min': n_min, 'n_max': n_max,
                'min_scenes': min_scenes, 'cluster_threshold': cluster_threshold,
            },
            'clusters': [
                {
                    'cluster_id': cl['cluster_id'],
                    'size': cl['size'],
                    'scene_count': cl['scene_count'],
                    'avg_similarity': cl['avg_similarity'],
                    'top_ngrams': cl['top_ngrams'],
                    'suggested_label': cl['suggested_label'],
                    'env_distribution': cl['env_distribution'],
                    'examples': [
                        {
                            'scene_id': ex['scene_id'],
                            'samples': [
                                {'ngram': s['ngram'], 'context': s['context']}
                                for s in ex['samples']
                            ],
                        }
                        for ex in cl['examples'][:3]
                    ],
                }
                for cl in enriched_clusters
            ],
        }
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
        print(f"\n[OK] 涌现模式已保存: {out_path}")


if __name__ == '__main__':
    main()
