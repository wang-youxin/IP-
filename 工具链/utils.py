"""
通用人物蒸馏框架 — 工具链公共模块
纯标准库，零外部依赖。
"""
import re
import os
import csv
import json
from pathlib import Path
from typing import Optional


def parse_frontmatter(content: str) -> dict:
    """解析 Markdown YAML frontmatter，返回 dict。"""
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return {}
    fm_text = match.group(1)
    fm = {}
    # 简单标量字段
    for key in ['id', 'type', 'title', 'status', 'canonical', 'version',
                 'created_at', 'updated_at', 'core_claim', 'claim_scope',
                 'why_it_matters', 'concept_definition', 'concept_function',
                 'concept_layer']:
        m = re.search(rf'^{key}:\s*(.+)$', fm_text, re.MULTILINE)
        if m:
            fm[key] = m.group(1).strip().strip('"').strip("'")
    # 列表字段
    for key in ['source_documents', 'source_authors', 'themes', 'keywords']:
        values = []
        in_list = False
        for line in fm_text.split('\n'):
            if re.match(rf'^{key}:\s*$', line.strip()):
                in_list = True
                continue
            if in_list:
                m = re.match(r'^\s+-\s+(.+)$', line)
                if m:
                    values.append(m.group(1).strip().strip('"').strip("'"))
                elif line.strip() and not line.startswith(' '):
                    break
        if values:
            fm[key] = values
    # relationships
    fm['_parsed_rels'] = _parse_relationships(fm_text)
    return fm


def _parse_relationships(fm_text: str) -> list:
    """解析 relationships 列表。"""
    rels = []
    lines = fm_text.split('\n')
    in_rels = False
    current = {}
    for line in lines:
        if re.match(r'^relationships:\s*', line):
            in_rels = True
            continue
        if in_rels:
            if line.strip().startswith('- type:'):
                if current.get('type'):
                    rels.append(current)
                current = {'type': re.sub(r'^- type:\s*', '', line.strip())}
            elif line.strip().startswith('target:'):
                current['target'] = re.sub(r'^\s*target:\s*', '', line.strip())
            elif line.strip().startswith('note:'):
                current['note'] = re.sub(r'^\s*note:\s*', '', line.strip())
            elif line.strip() == '':
                continue
            elif not line.startswith(' ') and not line.startswith('\t') and line.strip():
                break
    if current.get('type'):
        rels.append(current)
    return rels


def find_md_files(root: Path) -> list[Path]:
    """递归查找所有 .md 文件。"""
    files = []
    if root.exists():
        for entry in root.rglob('*.md'):
            if entry.is_file():
                files.append(entry)
    return files


def find_unit_files(base: Path, subdirs: list[str] = None) -> list[Path]:
    """在内容单元子目录中查找所有 .md 文件。
    如果未指定 subdirs，自动发现 02-内容单元库/ 下的所有子目录。
    """
    files = []
    if subdirs is None:
        unit_root = base / '02-内容单元库'
        if unit_root.exists():
            for d in unit_root.iterdir():
                if d.is_dir():
                    for f in d.glob('*.md'):
                        if f.is_file():
                            files.append(f)
        return files
    for sub in subdirs:
        d = base / '02-内容单元库' / sub
        if not d.exists():
            # 尝试大小写变体（如 CONCEPTS vs CON）
            unit_root = base / '02-内容单元库'
            if unit_root.exists():
                for real_dir in unit_root.iterdir():
                    if real_dir.is_dir() and real_dir.name.upper() == sub.upper():
                        d = real_dir
                        break
        if d.exists():
            for f in d.glob('*.md'):
                if f.is_file():
                    files.append(f)
    return files


def auto_discover_unit_subdirs(base: Path) -> list[str]:
    """自动发现 02-内容单元库/ 下的所有子目录名。"""
    unit_root = base / '02-内容单元库'
    if not unit_root.exists():
        return []
    return sorted([d.name for d in unit_root.iterdir() if d.is_dir()])


def extract_wiki_links(content: str) -> list[str]:
    """提取 [[链接]] 中的所有目标 ID。"""
    links = re.findall(r'\[\[([^\]|#]+)', content)
    return [l.strip() for l in links]


def escape_csv(val) -> str:
    """CSV 转义。"""
    s = str(val or '')
    return '"' + s.replace('"', '""') + '"'
