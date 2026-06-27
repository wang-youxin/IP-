#!/usr/bin/env python3
"""
methodology_conflict_checker.py — 方法论冲突检测器

检测同一人物的不同方法论之间的潜在冲突。
纯 Python 标准库，零外部依赖。

逻辑:
  1. 如果方法论A的触发条件与方法论B的触发条件重叠，但操作建议相反 → 冲突
  2. 如果方法论A的失效条件 = 方法论B的最佳条件 → 矛盾
  3. 检测方法论之间的未标注依赖（A 的操作破坏了 B 的触发条件）

输入: Phase 2 形式化操作模式（JSON 格式）
输出: 潜在冲突列表 + 严重度评级

JSON 输入格式（从 Phase 2 Step 2.2 输出提取）:
[
  {
    "name": "不对称回应",
    "definition": "不在对方设定的层面回应",
    "trigger": "对方提出一个框定好的问题",
    "action": "反向拆解提问本身的预设",
    "failure_conditions": ["对方真正需要信息而非诊断时", "紧急安全问题时"],
    "best_conditions": ["对方的问题隐含错误预设时"],
    "layer": "元规则",
    "depends_on": [],
    "star_rating": 5
  },
  ...
]

用法:
  python methodology_conflict_checker.py <项目目录> --methods <方法JSON>
  python methodology_conflict_checker.py D:/蒸馏项目/费曼 --methods phase2_methods.json --json
"""
import sys
import json
from pathlib import Path
from collections import defaultdict
from itertools import combinations


# ══════════════════════════════════════════════════════
# 冲突检测引擎
# ══════════════════════════════════════════════════════

def detect_trigger_overlap_conflicts(methods: list[dict]) -> list[dict]:
    """
    检测1: 触发条件重叠但操作相反。

    两个方法论的触发条件在语义上有重叠（简化版：共享关键词），
    但它们的 action 方向相反或互斥。
    """
    conflicts = []
    opposites = {
        '直接回答': ['反问', '不回答', '回避', '绕开', '反向拆解'],
        '反问': ['直接回答', '给出答案'],
        '扩大': ['缩小', '压缩', '限制'],
        '增加': ['减少', '压缩', '砍掉', '删除'],
        '主动': ['被动', '等待', '延迟'],
        '快速': ['慢速', '延迟', '等待'],
        '进入': ['退出', '回避', '不进入'],
        '打破': ['保持', '接受', '进入'],
        '开放': ['封闭', '拒绝', '限制'],
    }

    for a, b in combinations(methods, 2):
        # 检查触发条件重叠
        a_triggers = _tokenize(a.get('trigger', ''))
        b_triggers = _tokenize(b.get('trigger', ''))
        trigger_overlap = len(a_triggers & b_triggers) / max(len(a_triggers | b_triggers), 1)

        if trigger_overlap < 0.3:
            continue

        # 检查操作建议是否相反
        a_actions = _tokenize(a.get('action', ''))
        b_actions = _tokenize(b.get('action', ''))

        opposition_found = False
        opposition_reason = ''
        for a_act in a_actions:
            if a_act in opposites:
                for opp in opposites[a_act]:
                    if opp in b_actions:
                        opposition_found = True
                        opposition_reason = f"'{a_act}' vs '{opp}'"
                        break
            if opposition_found:
                break

        # 双向检查
        if not opposition_found:
            for b_act in b_actions:
                if b_act in opposites:
                    for opp in opposites[b_act]:
                        if opp in a_actions:
                            opposition_found = True
                            opposition_reason = f"'{opp}' vs '{b_act}'"
                            break
                if opposition_found:
                    break

        if opposition_found:
            severity = _assess_severity(a, b, trigger_overlap)
            conflicts.append({
                'type': 'trigger_overlap_opposite_action',
                'method_a': a['name'],
                'method_b': b['name'],
                'trigger_overlap': round(trigger_overlap, 3),
                'opposition': opposition_reason,
                'severity': severity,
                'recommendation': _recommend_opposite(a, b, trigger_overlap),
            })

    return conflicts


def detect_failure_best_conflicts(methods: list[dict]) -> list[dict]:
    """
    检测2: A 的失效条件 = B 的最佳条件。

    即方法论A说"在X情况下不要用我"，方法B说"在X情况下最适合用我"。
    这暗示 X 是一个关键决策点——此人在这里需要在两个方法间做选择。
    """
    conflicts = []

    for a, b in combinations(methods, 2):
        a_failures = set(_normalize_phrases(a.get('failure_conditions', [])))
        b_bests = set(_normalize_phrases(b.get('best_conditions', [])))

        overlap = a_failures & b_bests
        if overlap:
            conflicts.append({
                'type': 'failure_equals_best',
                'method_a': a['name'],
                'method_a_role': '失效条件',
                'method_b': b['name'],
                'method_b_role': '最佳条件',
                'overlap_conditions': sorted(overlap),
                'severity': 'medium',
                'recommendation': (
                    f"当条件 [{', '.join(sorted(overlap))}] 出现时，"
                    f"不能用「{a['name']}」但应该用「{b['name']}」。"
                    f"建议为此条件建立明确的决策规则。"
                ),
            })

        # 反向检查
        b_failures = set(_normalize_phrases(b.get('failure_conditions', [])))
        a_bests = set(_normalize_phrases(a.get('best_conditions', [])))
        overlap2 = b_failures & a_bests
        if overlap2:
            conflicts.append({
                'type': 'failure_equals_best',
                'method_a': b['name'],
                'method_a_role': '失效条件',
                'method_b': a['name'],
                'method_b_role': '最佳条件',
                'overlap_conditions': sorted(overlap2),
                'severity': 'medium',
                'recommendation': (
                    f"当条件 [{', '.join(sorted(overlap2))}] 出现时，"
                    f"不能用「{b['name']}」但应该用「{a['name']}」。"
                    f"建议为此条件建立明确的决策规则。"
                ),
            })

    return conflicts


def detect_dependency_conflicts(methods: list[dict]) -> list[dict]:
    """
    检测3: 方法论之间的依赖链断裂。

    如果 A 依赖 B，但 B 的操作在某个场景下会破坏 A 的触发条件。
    或者 A 声称依赖 B，但 B 的产出与 A 的触发条件互斥。
    """
    conflicts = []
    method_map = {m['name']: m for m in methods}

    for method in methods:
        for dep_name in method.get('depends_on', []):
            if dep_name not in method_map:
                conflicts.append({
                    'type': 'dependency_missing',
                    'method_a': method['name'],
                    'method_b': dep_name,
                    'severity': 'high',
                    'recommendation': f"「{method['name']}」声称依赖「{dep_name}」，但在方法列表中未找到。请检查是否遗漏了此方法论的提取。",
                })
                continue

            dep = method_map[dep_name]
            # 检查 A 的触发条件是否与 B 的失效条件重叠
            a_triggers = _tokenize(method.get('trigger', ''))
            b_failures = set(_normalize_phrases(dep.get('failure_conditions', [])))

            # 简化：检查触发条件的词是否出现在 B 的失效条件中
            for t in a_triggers:
                for bf in b_failures:
                    if t in bf:
                        conflicts.append({
                            'type': 'dependency_failure_overlap',
                            'method_a': method['name'],
                            'method_b': dep_name,
                            'detail': f"「{method['name']}」的触发条件包含「{t}」，但被依赖的「{dep_name}」的失效条件包含「{bf}」",
                            'severity': 'high',
                            'recommendation': f"「{method['name']}」在条件「{t}」下可能无法正常工作，因为它的依赖「{dep_name}」在此条件下会失效。需要检查依赖链是否成立。",
                        })

    return conflicts


def detect_missing_boundary(methods: list[dict]) -> list[dict]:
    """
    检测4: 两个方法的触发条件几乎相同但有不同的推荐行为。
    不是直接的相反（那会被检测1捕获），而是"不太一样"。
    暗示此人的方法论体系在这个交叉点上缺乏明确的决策边界。
    """
    conflicts = []
    threshold = 0.7  # 高重叠阈值

    for a, b in combinations(methods, 2):
        a_triggers = _tokenize(a.get('trigger', ''))
        b_triggers = _tokenize(b.get('trigger', ''))

        if not a_triggers or not b_triggers:
            continue

        overlap = len(a_triggers & b_triggers) / max(len(a_triggers | b_triggers), 1)
        if overlap >= threshold:
            # 检查操作是否不同
            a_actions = _tokenize(a.get('action', ''))
            b_actions = _tokenize(b.get('action', ''))

            action_diff = len(a_actions - b_actions) + len(b_actions - a_actions)
            if action_diff > 0:
                conflicts.append({
                    'type': 'ambiguous_boundary',
                    'method_a': a['name'],
                    'method_b': b['name'],
                    'trigger_overlap': round(overlap, 3),
                    'action_difference': action_diff,
                    'severity': 'low',
                    'recommendation': (
                        f"「{a['name']}」和「{b['name']}」的触发条件高度重叠（{overlap:.0%}），"
                        f"但行为不同。此人在这些场景下如何选择用哪个？建议补充明确的决策边界。"
                    ),
                })

    return conflicts


# ══════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════

STOP_WORDS = {
    '的', '是', '在', '了', '和', '与', '或', '不', '要', '会', '能', '可以',
    '如果', '当', '时', '时候', '这个', '那个', '一个', '一种', '什么', '怎么',
    '对方', '此人', '他', '她', '它', '他们', '进行', '使用', '通过', '针对',
    'the', 'a', 'an', 'is', 'are', 'when', 'if', 'then', 'for', 'to', 'of',
}


def _tokenize(text: str) -> set[str]:
    """简单中文分词（2-gram + 关键词提取）。"""
    text = text.lower().strip()
    # 提取 2-4 字词
    tokens = set()
    # 常见方法论关键词的手工提取
    for ch in '，,。.！!？?；;：:':
        text = text.replace(ch, ' ')
    words = text.split()
    for w in words:
        w = w.strip()
        if len(w) >= 2 and w not in STOP_WORDS:
            tokens.add(w)
    return tokens


def _normalize_phrases(phrases: list[str]) -> list[str]:
    """规范化短语列表，用于跨方法比较。"""
    result = []
    for p in phrases:
        p = p.strip().lower()
        # 去掉标点
        for ch in '，,。.！!？?；;：:':
            p = p.replace(ch, '')
        p = ' '.join(w for w in p.split() if w not in STOP_WORDS)
        if p:
            result.append(p)
    return result


def _assess_severity(a: dict, b: dict, overlap: float) -> str:
    """评估冲突严重度。"""
    # 公理层冲突 > 元规则层 > 操作层
    layer_weight = {'公理': 3, '元规则': 2, '操作': 1}
    a_w = layer_weight.get(a.get('layer', '操作'), 1)
    b_w = layer_weight.get(b.get('layer', '操作'), 1)
    combined = a_w + b_w + overlap * 2

    if combined >= 7:
        return 'critical'
    elif combined >= 5:
        return 'high'
    elif combined >= 3:
        return 'medium'
    return 'low'


def _recommend_opposite(a: dict, b: dict, overlap: float) -> str:
    """为触发重叠-操作相反冲突生成建议。"""
    a_layer = a.get('layer', '操作')
    b_layer = b.get('layer', '操作')

    if a_layer == '公理' and b_layer == '公理':
        return (
            f"⚠️ 两个公理层方法论存在冲突——这是最严重的信号。"
            f"需要检查：（1）推导链是否有误？（2）是否遗漏了关键的区分条件？"
            f"（3）此人是否真的同时持有这两个矛盾的公理？"
        )
    elif overlap > 0.7:
        return (
            f"触发条件高度重叠（{overlap:.0%}），但操作相反。"
            f"建议检查是否有一个隐含的区分条件未被提取，或其中一个是特定场景的变体。"
        )
    else:
        return (
            f"部分触发条件重叠——可能在不同场景下使用不同方法。"
            f"建议标注这两个方法的精确适用边界。"
        )


# ══════════════════════════════════════════════════════
# 主程序
# ══════════════════════════════════════════════════════

def load_methods(project_dir: Path, methods_file: str = None) -> list[dict]:
    """加载方法论 JSON。"""
    if not methods_file:
        # 尝试默认路径
        default_paths = [
            project_dir / '03-处理状态' / 'phase2_methods.json',
            project_dir / 'phase2_methods.json',
        ]
        for p in default_paths:
            if p.exists():
                data = json.loads(p.read_text(encoding='utf-8'))
                if isinstance(data, list):
                    return data
        return []

    mp = Path(methods_file)
    if not mp.is_absolute():
        mp = project_dir / mp
    if mp.exists():
        data = json.loads(mp.read_text(encoding='utf-8'))
        if isinstance(data, list):
            return data
    return []


def main():
    if len(sys.argv) < 2:
        print("用法: python methodology_conflict_checker.py <项目目录> [选项]")
        print()
        print("选项:")
        print("  --methods <文件>   方法论 JSON 文件路径")
        print("  --json             输出 JSON 格式")
        print()
        print("JSON 输入格式示例:")
        print("""[
  {
    "name": "不对称回应",
    "trigger": "对方提出一个框定好的问题",
    "action": "反向拆解提问本身的预设",
    "failure_conditions": ["对方真正需要信息时"],
    "best_conditions": ["对方的问题隐含错误预设时"],
    "layer": "元规则",
    "depends_on": []
  }
]""")
        sys.exit(1)

    project_dir = Path(sys.argv[1]).resolve()
    use_json = '--json' in sys.argv
    methods_file = None
    for i, arg in enumerate(sys.argv):
        if arg == '--methods' and i + 1 < len(sys.argv):
            methods_file = sys.argv[i + 1]

    methods = load_methods(project_dir, methods_file)
    if not methods:
        print("[FAIL] 未找到方法论数据。请使用 --methods 指定 JSON 文件。", file=sys.stderr)
        sys.exit(1)

    if not use_json:
        print(f"加载方法论: {len(methods)} 个")
        print(f"分析中...")

    # 执行四类检测
    t_overlap = detect_trigger_overlap_conflicts(methods)
    f_best = detect_failure_best_conflicts(methods)
    dep_conf = detect_dependency_conflicts(methods)
    ambiguous = detect_missing_boundary(methods)

    all_conflicts = t_overlap + f_best + dep_conf + ambiguous

    if use_json:
        output = {
            'total_methods': len(methods),
            'total_conflicts': len(all_conflicts),
            'by_type': {
                'trigger_overlap_opposite': len(t_overlap),
                'failure_equals_best': len(f_best),
                'dependency_conflict': len(dep_conf),
                'ambiguous_boundary': len(ambiguous),
            },
            'by_severity': {
                'critical': len([c for c in all_conflicts if c['severity'] == 'critical']),
                'high': len([c for c in all_conflicts if c['severity'] == 'high']),
                'medium': len([c for c in all_conflicts if c['severity'] == 'medium']),
                'low': len([c for c in all_conflicts if c['severity'] == 'low']),
            },
            'conflicts': all_conflicts,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"\n=== 方法论冲突检测报告 ===\n")
        print(f"方法论总数: {len(methods)}")
        print(f"检测到冲突: {len(all_conflicts)} 个")
        print(f"  触发重叠-操作相反: {len(t_overlap)}")
        print(f"  失效=最佳条件: {len(f_best)}")
        print(f"  依赖链断裂: {len(dep_conf)}")
        print(f"  边界模糊: {len(ambiguous)}")

        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        all_conflicts.sort(key=lambda c: severity_order.get(c['severity'], 9))

        if all_conflicts:
            for i, c in enumerate(all_conflicts, 1):
                sev_icon = {'critical': '🚫', 'high': '🔴', 'medium': '🟡', 'low': '🟢'}.get(c['severity'], '❓')
                print(f"\n--- 冲突 {i}: {sev_icon} [{c['severity'].upper()}] {c['type']} ---")
                if c['type'] == 'trigger_overlap_opposite_action':
                    print(f"  方法A: 「{c['method_a']}」vs 方法B: 「{c['method_b']}」")
                    print(f"  触发重叠: {c['trigger_overlap']:.1%}")
                    print(f"  操作相反: {c['opposition']}")
                elif c['type'] == 'failure_equals_best':
                    print(f"  「{c['method_a']}」的失效条件 = 「{c['method_b']}」的最佳条件")
                    print(f"  重叠条件: {c['overlap_conditions']}")
                elif c['type'].startswith('dependency'):
                    print(f"  {c.get('detail', '')}")
                elif c['type'] == 'ambiguous_boundary':
                    print(f"  「{c['method_a']}」↔「{c['method_b']}」触发重叠{c['trigger_overlap']:.1%}，行为不同")
                print(f"  建议: {c['recommendation']}")

        # 综合评级
        print(f"\n--- 综合评级 ---")
        critical_count = len([c for c in all_conflicts if c['severity'] == 'critical'])
        high_count = len([c for c in all_conflicts if c['severity'] == 'high'])
        if critical_count > 0:
            print(f"🚫 危险 — {critical_count} 个严重冲突。方法论体系存在结构性矛盾，建议回退 Phase 2 重新审查。")
        elif high_count > 2:
            print(f"🔴 警告 — {high_count} 个高优先级冲突。建议在 Phase 4 交叉分析中重点处理。")
        elif len(all_conflicts) > 0:
            print(f"🟡 注意 — {len(all_conflicts)} 个冲突。建议在诚实边界中记录。")
        else:
            print(f"🟢 未检测到冲突。")


if __name__ == '__main__':
    main()
