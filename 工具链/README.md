# 通用人物蒸馏框架 — 工具链

> 纯 Python 标准库，零外部依赖。Python 3.9+ 可用。

## 工具清单

| 工具 | 功能 | 对应框架 Phase |
|------|------|-------------|
| `init_project.py` | 初始化蒸馏项目骨架（目录+模板+规则） | Phase 0 准备 |
| `source_registry.py` | 自动扫描素材文件，分配 SRC-ID | Step 0.0 |
| `link_checker.py` | 死链/孤儿/双向性全量检查 | Step 2.9b |
| `coverage_scanner.py` | 素材引用覆盖率分析 | Phase 0 后 / Phase 5 前 |
| `relationship_analyzer.py` | 关系网络分析+结构洞发现 | Phase 4 前 |
| `health_report.py` | 综合健康报告（汇总以上全部） | Phase 5 发布前 |
| **🆕 `cooccurrence_analyzer.py`** | **共现网络中心性分析**：度中心性/介数中心性/特征向量中心性 + Louvain社区检测 | Phase -1.5 (Head 2) |
| **🆕 `cross_scene_detector.py`** | **跨场景行为模式检测**：滑动窗口+环境变异+统计显著性 | Phase 2 (辅助Step 2.0) |
| **🆕 `methodology_conflict_checker.py`** | **方法论冲突检测**：触发重叠/失效=最佳/依赖断裂/边界模糊 四类检测 | Phase 4 前 |
| **🆕 `pattern_emergence.py`** | **无监督模式涌现**：滑动窗口+N-gram+TF-IDF+层次聚类，自动发现跨场景重复模式簇，不预设行为标签 | Phase 2 前 |

## 使用流程

```bash
# 1. 初始化项目
python 工具链/init_project.py D:/蒸馏项目/费曼 --name 费曼

# 2. 复制原始素材到 01-原始素材区/（手动操作）

# 3. 自动生成素材注册表
python 工具链/source_registry.py D:/蒸馏项目/费曼 --prefix FM

# 4. 执行 Phase -1 语义切分 → 产出场景文档

# 5. 🆕 无监督模式涌现（自动发现跨场景重复模式，不预设标签）
python 工具链/pattern_emergence.py D:/蒸馏项目/费曼 --min-scenes 3 --cluster-threshold 0.4

# 6. 🆕 检测跨场景行为模式（辅助Phase 2扫描）
python 工具链/cross_scene_detector.py D:/蒸馏项目/费曼 --min-occurrences 3 --json

# 7. 执行 Phase 1-2（手动/AI 辅助）— 创建 CON/OPI/CAS/SOL/QST 文件

# 8. 🆕 共现网络分析（Head 2 权重计算）
python 工具链/cooccurrence_analyzer.py D:/蒸馏项目/费曼 --json

# 9. 🆕 方法论冲突检测（Phase 4前）
python 工具链/methodology_conflict_checker.py D:/蒸馏项目/费曼 --methods phase2_methods.json

# 10. 检查双链健康
python 工具链/link_checker.py D:/蒸馏项目/费曼

# 11. 检查素材覆盖率
python 工具链/coverage_scanner.py D:/蒸馏项目/费曼

# 12. 分析关系网络
python 工具链/relationship_analyzer.py D:/蒸馏项目/费曼 --csv

# 13. 生成综合健康报告
python 工具链/health_report.py D:/蒸馏项目/费曼
```

## 输出格式

所有工具支持两种输出：
- **人类可读**: 默认，直接打印到终端
- **机器可读**: `--json` 标志，输出 JSON 供其他工具解析

## 门禁集成

```bash
# CI/CD 中使用 JSON 输出判断门禁
python 工具链/link_checker.py D:/项目 --json | python -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d['passed'] else 1)"
```

## 与鲁大魔库工具链的对应

| 鲁大魔库脚本 (JS) | 本工具链 (Python) |
|------------------|-----------------|
| `init-content-system.js` | `init_project.py` |
| `generate-source-registry.js` | `source_registry.py` |
| `generate-link-map.js` | `link_checker.py` |
| `scan-ld-coverage.js` | `coverage_scanner.py` |
| `analyze-relationships.js` | `relationship_analyzer.py` |
| `summarize-system.js` | `health_report.py` |
