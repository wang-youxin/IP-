#!/usr/bin/env python3
"""
cross_scene_detector.py — 跨场景重复行为模式检测器

辅助 Phase 2 Step 2.0，自动检测跨场景的重复行为模式。
纯 Python 标准库，零外部依赖。

算法:
  1. 滑动窗口 — 在不同场景中搜索相似的行为序列
  2. 环境对比 — 同一模式在环境A vs 环境B下的变异度
  3. 统计显著性 — 基于二项分布检验模式出现次数是否显著超过随机基线

输入: 场景文档目录（SCN-*.md，含 YAML frontmatter with 六维环境标签）
输出: 候选涌现模式列表 + 跨场景一致性分数

用法:
  python cross_scene_detector.py <项目目录> [选项]
  python cross_scene_detector.py D:/蒸馏项目/费曼 --json --min-occurrences 3
"""
import sys
import json
import re
from pathlib import Path
from collections import defaultdict, Counter
from math import sqrt, comb as binomial_coeff


sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import parse_frontmatter


# ══════════════════════════════════════════════════════
# 行为序列提取
# ══════════════════════════════════════════════════════

# 行为信号词（此人主动发出的动作）
ACTION_PATTERNS = [
    # 干预型 — 面对外部输入的固定反应
    (r'(反问|追问道|反问道|反将|不直接回答|打断道|插话道|劈头问)', '反问/打断/不直接回答'),
    (r'(你刚才说的|你说的这个|你先说一下|你先定义|你先告诉我|你意思是)', '要求对方先澄清/定义'),
    (r'(我举个例子|比如说|好比说|你想想|假设|想象一下)', '用类比/举例回应'),
    (r'(不对|不是|你错了|这个说法有问题|这是误解|你理解错了)', '直接否定/纠正'),

    # 产出型 — 创造/生产东西时的固定流程
    (r'(先.*再.*最后|第一步.*第二步|首先.*然后.*接着|第一.*第二.*第三)', '结构化分步'),
    (r'(核心是|关键是|本质是|归根结底|说到底|一句话)', '压缩/提炼本质'),
    (r'(我一般|我通常|我的习惯是|我的方法|我都是)', '自我描述固定流程'),
    (r'(砍掉|删掉|去掉|不做|放弃|简化|压缩)', '砍掉/简化/放弃'),

    # 判断型 — 做选择时的固定标准
    (r'(有没有可能|能不能|会不会|是不是|行不行)', '可能性判断'),
    (r'(值不值|划不划算|值钱吗|值这个价吗|值回票价)', '价值判断'),
    (r'(看人|看这个人|看对方|判断一下|一眼就看出)', '人物判断'),

    # 维护型 — 维持自身状态的固定操作
    (r'(定期|每天|每周|每个月|经常|习惯性)', '定期/高频行为'),
    (r'(复盘|回顾|反思|回头想|后来想|总结)', '复盘/反思'),

    # 互动型 — 与人交流的固定模式
    (r'(沉默|停顿|不说话|想了.*秒|思考了片刻)', '沉默/停顿'),
    (r'(你问他|让他说|你先说|听他说完|等他说)', '让对方先说/倾听'),
]

# 环境标签映射
ENV_DIMS = ['physical', 'social', 'emotional', 'trigger', 'pressure', 'role']


def extract_behavior_sequences(scene_file: Path) -> list[dict]:
    """
    从单个场景文档中提取行为序列。

    返回:
      [{
        'scene_id': 'SCN-XX-001-01',
        'position': 0,               # 在场景中的相对位置
        'behavior_type': '反问/打断/不直接回答',
        'context_50chars': '...',    # 前后50字符上下文
        'env': {物理/社交/情绪/触发/压力/角色}
      }, ...]
    """
    content = scene_file.read_text(encoding='utf-8')
    fm = parse_frontmatter(content)
    scene_id = fm.get('id', scene_file.stem)

    # 提取环境标签（从 frontmatter + 正文中的六维分析）
    env = _extract_env_tags(fm, content)

    # 去掉 frontmatter 后提取行为
    body = re.sub(r'^---.*?---', '', content, flags=re.DOTALL)
    behaviors = []

    for pattern, btype in ACTION_PATTERNS:
        for match in re.finditer(pattern, body):
            start = max(0, match.start() - 50)
            end = min(len(body), match.end() + 50)
            behaviors.append({
                'scene_id': scene_id,
                'position': match.start() / max(len(body), 1),
                'behavior_type': btype,
                'matched_text': match.group(0)[:80],
                'context_50chars': body[start:end].replace('\n', ' '),
                'env': env,
            })

    return behaviors


def _extract_env_tags(fm: dict, content: str) -> dict:
    """从 frontmatter 和正文六维分析中提取环境标签。"""
    env = {
        'physical': '未知',
        'social': '未知',
        'emotional': '未知',
        'trigger': '未知',
        'pressure': '未知',
        'role': '未知',
    }

    # 从 frontmatter 提取
    for dim in ENV_DIMS:
        key = f'env_{dim}'
        if key in fm:
            env[dim] = fm[key]

    # 从 scene_type 推断部分环境
    scene_type = fm.get('scene_type', '')
    type_to_env = {
        '对话问答': {'social': '问答互动', 'trigger': '对方提问'},
        '单人讲述': {'social': '独白/输出', 'trigger': '此人主动发起'},
        '实战诊断': {'social': '诊断互动', 'role': '诊断者'},
        '争论冲突': {'social': '有对立', 'pressure': '高'},
        '闲谈互动': {'social': '随意交流', 'pressure': '低'},
        '演讲展示': {'social': '一对多输出', 'role': '展示者'},
        '写作输出': {'physical': '书写环境', 'social': '独处'},
        '复盘反思': {'role': '反思者', 'trigger': '回顾过去'},
    }
    if scene_type in type_to_env:
        for k, v in type_to_env[scene_type].items():
            if env.get(k, '未知') == '未知':
                env[k] = v

    return env


# ══════════════════════════════════════════════════════
# 跨场景模式检测
# ══════════════════════════════════════════════════════

def cluster_behaviors(all_behaviors: list[dict], min_occurrences: int = 3) -> list[dict]:
    """
    按行为类型聚类，计算每个类型的跨场景出现次数和环境变异度。
    """
    by_type = defaultdict(list)
    for b in all_behaviors:
        by_type[b['behavior_type']].append(b)

    patterns = []
    total_scenes = len(set(b['scene_id'] for b in all_behaviors))

    for btype, behaviors in by_type.items():
        scenes = set(b['scene_id'] for b in behaviors)
        scene_count = len(scenes)
        total_occur = len(behaviors)

        if scene_count < min_occurrences:
            continue

        # 环境变异分析
        env_variation = _compute_env_variation(behaviors)

        # 统计显著性（简化二项检验）
        # 零假设：此行为在场景中随机出现，概率 = 行为出现次数 / 总场景数
        base_rate = total_occur / max(total_scenes, 1)
        is_significant = _binomial_test(scene_count, total_scenes, base_rate, threshold=0.01)

        patterns.append({
            'behavior_type': btype,
            'total_occurrences': total_occur,
            'scene_count': scene_count,
            'scene_ids': sorted(scenes),
            'cross_scene_rate': round(scene_count / max(total_scenes, 1), 3),
            'env_variation': env_variation,
            'cross_scene_consistency': round(
                1.0 - env_variation['variation_score'], 3
            ),
            'statistically_significant': is_significant,
            'examples': [
                {
                    'scene_id': b['scene_id'],
                    'matched': b['matched_text'],
                    'context': b['context_50chars'][:100],
                }
                for b in behaviors[:5]
            ],
            'env_breakdown': _compute_env_breakdown(behaviors),
        })

    # 按跨场景出现次数降序
    patterns.sort(key=lambda x: -x['scene_count'])
    return patterns


def _compute_env_variation(behaviors: list[dict]) -> dict:
    """
    计算同一行为类型在不同环境维度下的变异度。

    变异度 = 1 - (同一维度下最常见值的出现占比)
    高变异度 → 此行为跨环境稳定出现（好——说明是通用模式）
    低变异度 → 此行为只在特定环境下出现（可能是环境触发而非稳定模式）
    """
    variation = {}
    total_variation = 0.0
    dims_present = 0

    for dim in ENV_DIMS:
        values = [b['env'].get(dim, '未知') for b in behaviors if b['env'].get(dim, '未知') != '未知']
        if len(values) < 2:
            variation[dim] = {'score': 0.0, 'dominant': '未知', 'values': {}}
            continue

        counter = Counter(values)
        dominant_count = counter.most_common(1)[0][1]
        # 变异分数：1 = 完全均匀（跨环境稳定），0 = 完全集中在单一环境
        score = 1.0 - (dominant_count / len(values))
        variation[dim] = {
            'score': round(score, 3),
            'dominant': counter.most_common(1)[0][0],
            'values': dict(counter.most_common()),
        }
        total_variation += score
        dims_present += 1

    variation['variation_score'] = round(
        total_variation / max(dims_present, 1), 3
    )
    return variation


def _compute_env_breakdown(behaviors: list[dict]) -> dict:
    """按环境维度分解行为分布。"""
    breakdown = {}
    for dim in ENV_DIMS:
        counter = Counter(b['env'].get(dim, '未知') for b in behaviors)
        breakdown[dim] = dict(counter.most_common())
    return breakdown


def _binomial_test(observed: int, total: int, base_rate: float, threshold: float = 0.01) -> bool:
    """
    简化二项检验。
    零假设：每个场景以 base_rate 的概率出现此行为。
    如果 observed 次场景出现此行为的概率 < threshold → 显著。
    """
    if total == 0 or base_rate >= 1.0:
        return observed >= 3  # 至少3个场景就算显著
    if base_rate == 0:
        return observed > 0

    # 计算 P(X >= observed) = 1 - P(X < observed)
    prob = 0.0
    for k in range(observed):
        if k > total:
            break
        prob += binomial_coeff(total, k) * (base_rate ** k) * ((1 - base_rate) ** (total - k))
    p_value = 1.0 - prob
    return p_value < threshold


# ══════════════════════════════════════════════════════
# 跨场景关联检测
# ══════════════════════════════════════════════════════

def detect_cross_scene_correlations(patterns: list[dict]) -> list[dict]:
    """
    检测两个行为模式是否倾向于在相同场景中共同出现。
    使用简化的 Jaccard 系数。
    """
    correlations = []
    for i, pa in enumerate(patterns):
        scenes_a = set(pa['scene_ids'])
        for j, pb in enumerate(patterns):
            if j <= i:
                continue
            scenes_b = set(pb['scene_ids'])
            intersection = len(scenes_a & scenes_b)
            union = len(scenes_a | scenes_b)
            if union == 0:
                continue
            jaccard = intersection / union
            if jaccard >= 0.5:  # 至少50%的场景重叠
                correlations.append({
                    'behavior_a': pa['behavior_type'],
                    'behavior_b': pb['behavior_type'],
                    'jaccard_similarity': round(jaccard, 3),
                    'shared_scenes': sorted(scenes_a & scenes_b)[:10],
                    'interpretation': (
                        f"「{pa['behavior_type']}」和「{pb['behavior_type']}」"
                        f"在 {intersection} 个场景中共同出现——可能互为因果或共享触发条件。"
                    ),
                })

    correlations.sort(key=lambda x: -x['jaccard_similarity'])
    return correlations


# ══════════════════════════════════════════════════════
# 主程序
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


def main():
    if len(sys.argv) < 2:
        print("用法: python cross_scene_detector.py <项目目录> [选项]")
        print()
        print("选项:")
        print("  --min-occurrences <N>  最少跨场景出现次数（默认 3）")
        print("  --json                 输出 JSON 格式")
        print()
        print("示例:")
        print("  python cross_scene_detector.py D:/蒸馏项目/费曼")
        print("  python cross_scene_detector.py D:/蒸馏项目/费曼 --min-occurrences 5 --json")
        sys.exit(1)

    project_dir = Path(sys.argv[1]).resolve()
    use_json = '--json' in sys.argv

    min_occ = 3
    for i, arg in enumerate(sys.argv):
        if arg == '--min-occurrences' and i + 1 < len(sys.argv):
            try:
                min_occ = int(sys.argv[i + 1])
            except ValueError:
                pass

    scenes = load_scene_docs(project_dir)
    if not scenes:
        print("[FAIL] 未找到场景文档（SCN-*.md）。请先执行 Phase -1 语义切分。", file=sys.stderr)
        sys.exit(1)

    if not use_json:
        print(f"场景文档: {len(scenes)} 个")
        print(f"最少出现次数: {min_occ}")
        print(f"分析中...")

    # 提取所有行为序列
    all_behaviors = []
    for sf in scenes:
        all_behaviors.extend(extract_behavior_sequences(sf))

    if not use_json:
        print(f"检测到行为信号: {len(all_behaviors)} 条")

    if len(all_behaviors) < min_occ:
        print(f"[WARN] 行为信号不足 {min_occ} 条。", file=sys.stderr)
        if use_json:
            print(json.dumps({'patterns': [], 'warning': 'insufficient_signals'}, ensure_ascii=False))
        sys.exit(0)

    # 跨场景聚类
    patterns = cluster_behaviors(all_behaviors, min_occurrences=min_occ)
    correlations = detect_cross_scene_correlations(patterns)

    if use_json:
        output = {
            'total_scenes': len(scenes),
            'total_behavior_signals': len(all_behaviors),
            'pattern_count': len(patterns),
            'patterns': [
                {
                    'behavior_type': p['behavior_type'],
                    'total_occurrences': p['total_occurrences'],
                    'scene_count': p['scene_count'],
                    'cross_scene_rate': p['cross_scene_rate'],
                    'variation_score': p['env_variation']['variation_score'],
                    'consistency': p['cross_scene_consistency'],
                    'significant': p['statistically_significant'],
                    'scenes': p['scene_ids'],
                    'examples': p['examples'],
                    'env_breakdown': p['env_breakdown'],
                }
                for p in patterns
            ],
            'correlations': correlations,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"\n=== 跨场景行为模式检测报告 ===\n")
        print(f"场景总数: {len(scenes)}")
        print(f"行为信号总数: {len(all_behaviors)}")
        print(f"候选涌现模式: {len(patterns)} 个 （跨≥{min_occ}个场景）")

        if correlations:
            print(f"跨场景关联: {len(correlations)} 对")

        print(f"\n--- 候选涌现模式 ---")
        for i, p in enumerate(patterns, 1):
            sig_mark = '✅' if p['statistically_significant'] else '⚠️'
            print(f"\n{i}. {sig_mark} {p['behavior_type']}")
            print(f"   出现: {p['total_occurrences']}次 / {p['scene_count']}个场景（跨场景率: {p['cross_scene_rate']:.1%}）")
            print(f"   环境变异度: {p['env_variation']['variation_score']:.2f}（{'高' if p['env_variation']['variation_score'] > 0.5 else '低'}变异 → "
                  f"{'跨环境稳定' if p['env_variation']['variation_score'] > 0.5 else '环境特定'}）")

            # 环境分布
            env_dominant = []
            for dim in ENV_DIMS:
                if dim in p['env_breakdown'] and p['env_breakdown'][dim]:
                    top_val = list(p['env_breakdown'][dim].keys())[0]
                    env_dominant.append(f"{dim}={top_val}")
            print(f"   环境分布: {', '.join(env_dominant)}")

            # 示例
            if p['examples']:
                print(f"   示例: [{p['examples'][0]['scene_id']}] \"{p['examples'][0]['matched']}\"")

        if correlations:
            print(f"\n--- 跨场景行为关联 ---")
            for c in correlations[:10]:
                print(f"  「{c['behavior_a']}」↔「{c['behavior_b']}」(Jaccard={c['jaccard_similarity']:.2f})")
                print(f"    {c['interpretation']}")

        # 输出候选模式到 JSON（供 Phase 2 使用）
        out_path = project_dir / '03-处理状态' / 'candidate_patterns.json'
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump({
                'patterns': [
                    {
                        'behavior_type': p['behavior_type'],
                        'total_occurrences': p['total_occurrences'],
                        'scene_count': p['scene_count'],
                        'cross_scene_rate': p['cross_scene_rate'],
                        'variation_score': p['env_variation']['variation_score'],
                        'scene_ids': p['scene_ids'],
                        'significant': p['statistically_significant'],
                    }
                    for p in patterns
                ],
                'correlations': correlations,
            }, f, ensure_ascii=False, indent=2)
        print(f"\n[OK] 候选模式已保存: {out_path}")


if __name__ == '__main__':
    main()
