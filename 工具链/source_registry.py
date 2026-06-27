#!/usr/bin/env python3
"""
source_registry.py — 素材注册表自动生成

扫描 01-原始素材区/ 中的所有文件，自动分配 SRC-ID。
与已有注册表合并（保留已有 ID）。

用法:
  python source_registry.py <项目目录> [--prefix XX]

示例:
  python source_registry.py D:/蒸馏项目/费曼 --prefix FM
"""
import sys
import re
from pathlib import Path
from datetime import date

# 将工具链目录加入 path 以便导入 utils
sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import escape_csv


# 文件扩展名 → 素材类型映射
EXT_TYPE_MAP = {
    '.md': '文本',
    '.txt': '文本',
    '.srt': '字幕',
    '.json': '数据',
    '.csv': '数据',
    '.pdf': 'PDF',
    '.docx': 'Word',
    '.mp4': '视频',
    '.mp3': '音频',
    '.wav': '音频',
    '.jpg': '图片',
    '.png': '图片',
    '.html': '网页',
}

# 路径关键词 → 素材类型
PATH_TYPE_HINTS = [
    (['对话', '连麦', 'dialogue', 'live'], '对话'),
    (['著作', '书籍', 'book', '书'], '著作'),
    (['访谈', '采访', 'interview'], '访谈'),
    (['演讲', 'speech', 'lecture', 'keynote'], '演讲'),
    (['社交', 'twitter', '微博', '即刻', 'tweet'], '社交媒体'),
    (['论文', 'paper', '专利', 'patent'], '学术'),
    (['代码', 'code', 'repo'], '代码'),
    (['内部', '备忘录', 'memo', '邮件', 'email'], '内部文档'),
    (['传记', '分析', '批评', 'review'], '二手分析'),
    (['视频', 'video', '录屏'], '视频'),
    (['播客', 'podcast', '音频', 'audio'], '音频'),
]


def infer_type(filepath: str) -> str:
    """从文件路径和扩展名推断素材类型。"""
    lower = filepath.lower()
    for keywords, typename in PATH_TYPE_HINTS:
        if any(kw in lower for kw in keywords):
            return typename
    ext = Path(filepath).suffix.lower()
    return EXT_TYPE_MAP.get(ext, '未分类')


def load_existing_registry(registry_path: Path) -> dict:
    """加载已有注册表，返回 {path: source_id} 和已用 ID 集合。"""
    by_path = {}
    max_seq = {}
    used_ids = set()
    if not registry_path.exists():
        return by_path, max_seq, used_ids

    with open(registry_path, 'r', encoding='utf-8') as f:
        reader = f.readlines()
    for line in reader[1:]:  # skip header
        parts = _parse_csv_line(line)
        if len(parts) >= 2:
            sid, relpath = parts[0].strip(), parts[1].strip()
            if sid and relpath:
                by_path[relpath] = sid
                used_ids.add(sid)
                m = re.match(r'SRC-(\w+)-(\d+)', sid)
                if m:
                    code = m.group(1)
                    seq = int(m.group(2))
                    max_seq[code] = max(max_seq.get(code, 0), seq)
    return by_path, max_seq, used_ids


def _parse_csv_line(line: str) -> list[str]:
    """简易 CSV 行解析。"""
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


def assign_id(relpath: str, by_path: dict, max_seq: dict, used_ids: set, prefix: str) -> str:
    """为素材路径分配 SRC-ID。"""
    if relpath in by_path:
        return by_path[relpath]

    # 尝试从文件名提取序号
    stem = Path(relpath).stem
    seq_match = re.match(r'^(\d{3})(\D|$)', stem)
    if seq_match:
        code = prefix
        seq = int(seq_match.group(1))
        candidate = f"SRC-{code}-{seq:03d}"
        if candidate not in used_ids:
            used_ids.add(candidate)
            max_seq[code] = max(max_seq.get(code, 0), seq)
            return candidate

    # 自动递进
    code = prefix
    next_seq = max_seq.get(code, 0) + 1
    while True:
        candidate = f"SRC-{code}-{next_seq:03d}"
        if candidate not in used_ids:
            used_ids.add(candidate)
            max_seq[code] = next_seq
            return candidate
        next_seq += 1


def main():
    if len(sys.argv) < 2:
        print("用法: python source_registry.py <项目目录> [--prefix XX]")
        sys.exit(1)

    project_dir = Path(sys.argv[1]).resolve()
    prefix = "XX"
    for i, a in enumerate(sys.argv):
        if a == '--prefix' and i + 1 < len(sys.argv):
            prefix = sys.argv[i + 1]

    source_dir = project_dir / "01-原始素材区"
    state_dir = project_dir / "03-处理状态"
    registry_path = state_dir / "来源注册表.csv"

    if not source_dir.exists():
        print(f"[ERROR] 素材目录不存在: {source_dir}")
        sys.exit(1)

    state_dir.mkdir(parents=True, exist_ok=True)
    by_path, max_seq, used_ids = load_existing_registry(registry_path)

    # 扫描所有文件
    files = []
    for f in source_dir.rglob('*'):
        if f.is_file() and not f.name.startswith('.') and not f.name.startswith('_'):
            rel = str(f.relative_to(source_dir)).replace('\\', '/')
            files.append(rel)

    files.sort()

    # 生成注册表
    rows = [['source_id', 'path', 'source_type', 'author', 'status', 'notes']]
    new_count = 0
    for rel in files:
        sid = assign_id(rel, by_path, max_seq, used_ids, prefix)
        stype = infer_type(rel)
        is_new = rel not in by_path
        if is_new:
            new_count += 1
        rows.append([sid, rel, stype, '待填', '候选' if is_new else '已确认',
                      '自动生成' if is_new else ''])

    csv_content = '\n'.join(
        ','.join(escape_csv(c) for c in row) for row in rows
    ) + '\n'
    registry_path.write_text(csv_content, encoding='utf-8')

    # 统计
    print(f"素材注册表: {registry_path}")
    print(f"总素材: {len(files)}")
    print(f"新增: {new_count}")
    print(f"已有: {len(files) - new_count}")
    print(f"SRC-ID 前缀: SRC-{prefix}-XXX")

    # 输出素材类型分布
    types = {}
    for row in rows[1:]:
        t = row[2]
        types[t] = types.get(t, 0) + 1
    print("\n素材类型分布:")
    for t, c in sorted(types.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")


if __name__ == '__main__':
    main()
