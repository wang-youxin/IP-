#!/usr/bin/env python3
"""
init_project.py — 初始化蒸馏项目骨架

用法:
  python init_project.py <目标目录> [--name 人物名]

示例:
  python init_project.py D:/蒸馏项目/费曼 --name 费曼
"""
import sys
import os
from pathlib import Path
from datetime import date


DIRS = [
    "00-规则与索引",
    "01-原始素材区",
    "02-内容单元库/CON",
    "02-内容单元库/OPI",
    "02-内容单元库/CAS",
    "02-内容单元库/SOL",
    "02-内容单元库/QST",
    "03-处理状态",
    "04-模板",
    "05-主题地图",
    "06-选题装配",
    "07-脚本与工具",
]

RULES = {
    "00-规则与索引/内容单元字段规范.md": """# 内容单元字段规范

## 必填字段（YAML frontmatter）
- id: 唯一标识（CON-XXX / OPI-XXX / CAS-XXX / SOL-XXX / QST-XXX）
- type: 单元类型（概念单元 / 观点单元 / 案例单元 / 方案单元 / 问题单元）
- title: 标题
- source_documents: 来源素材ID列表
- status: 状态（已确认 / 待核对 / 推测）

## 可选字段
- themes: 主题标签
- keywords: 关键词
- version: 版本号
- created_at / updated_at: 日期

## 关系字段
- relationships: 关系列表（type + target + note）
""",

    "00-规则与索引/内容单元关系规则.md": """# 内容单元关系规则

## 五种关系类型
- `回应`: A 直接回应 B（如 OPI 回应 QST）
- `解释`: A 解释了 B 的原理/机制（如 CON 解释 OPI）
- `证明`: A 是 B 的具体证据（如 CAS 证明 OPI）
- `冲突`: A 与 B 存在矛盾
- `依赖`: A 依赖于 B（如 CON 依赖其他 CON）

## 方向纪律
- `解释` 优先由概念单元指向被解释对象
- `证明` 优先由案例单元指向被证明对象
- `回应` 由回应方指向被回应对象
- `冲突` 建议双向建立

## 强度评级
- ★★★ 强关系：原文直接支持
- ★★☆ 中关系：主题共享，逻辑相关
- ★☆☆ 弱关系：推断关联
""",

    "00-规则与索引/处理流程.md": """# 处理流程

## Phase 0: 素材诊断
1. 素材注册 → 分配 SRC-ID
2. 素材清点与分类
3. 内容方向判定
4. 素材质量评级
5. 人物类型判定
6. 运行红色判断规则 → 输出维度激活清单

## Phase 1-5
按 `蒸馏流水线-提示词架构.md` 执行。
""",
}

STATE_FILES = {
    "03-处理状态/来源注册表.csv": "source_id,path,source_type,author,status,notes\n",
    "03-处理状态/原始素材索引.csv": "path,category\n",
    "03-处理状态/待处理清单.csv": "path,status,source_type,notes\n",
    "03-处理状态/已处理清单.csv": "path,status,source_type,notes\n",
    "03-处理状态/关系索引.csv": "source_id,source_type,source_title,relation_type,target_id,target_type,target_title,note,source_file,target_file,status\n",
    "03-处理状态/处理状态总览.md": "# 处理状态总览\n\n最后更新：待补\n\n## 当前进度\n- 项目骨架已建立\n- 待导入原始素材\n\n## 下一步\n- 复制原始素材到 01-原始素材区/\n- 运行 source_registry.py 生成 SRC-ID\n",
    "03-处理状态/抽取日志.md": "# 抽取日志\n",
}

UNIT_TEMPLATES = {
    "04-模板/CON模板.md": """---
id: CON-XXX
type: 概念单元
title: [概念名]
source_documents:
  - SRC-XX-001
themes:
  - [主题]
keywords:
  - [关键词]
status: 待核对
canonical: true
version: 1
created_at: YYYY-MM-DD
concept_definition: "[一句话定义]"
concept_function: "[这个概念解释了什么/用来做什么]"
concept_layer: [公理层/操作层/身份层/传播层/业务层/策略层]
relationships:
  - type: 解释
    target: OPI-XXX
    note: ""
---

## 核心内容
[此概念的核心特征、应用方式]

## 来源依据
SRC-XX-001: "[原文]"

## 典型应用
1. [场景] → [应用方式] — SRC-XX-XXX
2. ...

## 关联单元
[[OPI-XXX]] [[CAS-XXX]]
""",

    "04-模板/OPI模板.md": """---
id: OPI-XXX
type: 观点单元
title: [观点标题]
source_documents:
  - SRC-XX-001
themes:
  - [主题]
keywords:
  - [关键词]
status: 待核对
canonical: true
version: 1
created_at: YYYY-MM-DD
core_claim: "[核心观点一句话]"
claim_scope: "[此观点适用于什么范围]"
why_it_matters: "[为什么这个观点重要]"
relationships:
  - type: 回应
    target: QST-XXX
    note: ""
---

## 核心内容
[观点展开]

## 来源依据
SRC-XX-001: "[原文]"

## 关联单元
[[CON-XXX]] [[OPI-XXX]] [[CAS-XXX]]
""",

    "04-模板/CAS模板.md": """---
id: CAS-XXX
type: 案例单元
title: [案例名]
source_documents:
  - SRC-XX-001
themes:
  - [主题]
keywords:
  - [关键词]
status: 待核对
canonical: true
version: 1
created_at: YYYY-MM-DD
relationships:
  - type: 证明
    target: OPI-XXX
    note: ""
---

## 事件背景
[谁/什么时候/发生了什么]

## 此人分析
SRC-XX-001: "[此人对此事件的原文分析]"

## 提炼原则
[此人从此事件中学到了什么]

## 关联单元
[[OPI-XXX]] [[CON-XXX]]
""",

    "04-模板/SOL模板.md": """---
id: SOL-XXX
type: 方案单元
title: [方案名]
source_documents:
  - SRC-XX-001
themes:
  - [主题]
keywords:
  - [关键词]
status: 待核对
canonical: true
version: 1
created_at: YYYY-MM-DD
relationships:
  - type: 回应
    target: QST-XXX
    note: ""
---

## 操作步骤
1. [步骤1]
2. [步骤2]
...

## 适用条件
[什么情况下适用]

## 来源依据
SRC-XX-001: "[原文]"
""",

    "04-模板/QST模板.md": """---
id: QST-XXX
type: 问题单元
title: [问题类型名]
source_documents:
  - SRC-XX-001
themes:
  - [主题]
keywords:
  - [关键词]
status: 待核对
canonical: true
version: 1
created_at: YYYY-MM-DD
---

## 识别信号
[怎么一眼识别这类问题]

## 底层逻辑
[这类问题的本质是什么]

## 此人拆解方法
[此人怎么拆这类问题]

## 典型示例
SRC-XX-001: "[原文]"
""",
}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--name')]
    name = "未命名"
    for i, a in enumerate(sys.argv[1:]):
        if a == '--name' and i + 1 < len(sys.argv) - 1:
            name = sys.argv[i + 2]
            break

    if len(args) < 1:
        print("用法: python init_project.py <目标目录> [--name 人物名]")
        sys.exit(1)

    target = Path(args[0]).resolve()
    print(f"初始化蒸馏项目: {target}")
    print(f"人物: {name}")

    # 建目录
    for d in DIRS:
        (target / d).mkdir(parents=True, exist_ok=True)
        print(f"  [OK] {d}")

    # 写规则文件
    for rel_path, content in RULES.items():
        p = target / rel_path
        if not p.exists():
            p.write_text(content, encoding='utf-8')
            print(f"  [OK] {rel_path}")

    # 写状态文件
    for rel_path, content in STATE_FILES.items():
        p = target / rel_path
        if not p.exists():
            p.write_text(content, encoding='utf-8')
            print(f"  [OK] {rel_path}")

    # 写模板
    for rel_path, content in UNIT_TEMPLATES.items():
        p = target / rel_path
        if not p.exists():
            p.write_text(content, encoding='utf-8')
            print(f"  [OK] {rel_path}")

    # 根目录文件
    readme = f"""# {name} 蒸馏项目

> 基于通用人物蒸馏框架 v3.2
> 初始化: {date.today().isoformat()}

## 目录
- `01-原始素材区/` — 原始素材副本
- `02-内容单元库/` — CON/OPI/CAS/SOL/QST
- `05-主题地图/` — 跨单元分析
- `03-处理状态/` — 进度追踪

## 当前状态
- 项目骨架已建立
- 下一步: 导入原始素材
"""
    (target / "README.md").write_text(readme, encoding='utf-8')
    print(f"  [OK] README.md")

    print(f"\n[OK] 项目骨架已建立: {target}")
    print(f"下一步: 将原始素材复制到 {target / '01-原始素材区/'}")


if __name__ == '__main__':
    main()
