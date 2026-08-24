import os
import ast
import sys
import argparse

# 大文件阈值（字节），默认 50MB
MAX_FILE_SIZE = 50 * 1024 * 1024

class CodeStats(ast.NodeVisitor):
    def __init__(self):
        self.class_count = 0
        self.function_count = 0   # 顶层函数
        self.method_count = 0     # 类内方法
        self.current_class = None

    def visit_ClassDef(self, node):
        self.class_count += 1
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = None

    def visit_FunctionDef(self, node):
        if self.current_class is None:
            self.function_count += 1
        else:
            self.method_count += 1
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        if self.current_class is None:
            self.function_count += 1
        else:
            self.method_count += 1
        self.generic_visit(node)

def analyze_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=filepath)
    except SyntaxError as e:
        print(f"⚠️ 跳过 {filepath}（语法错误: {e}）")
        return None
    stats = CodeStats()
    stats.visit(tree)
    return stats

def collect_stats(file_list):
    result = {
        'files': 0,
        'classes': 0,
        'functions': 0,
        'methods': 0,
    }
    for fpath in file_list:
        stats = analyze_file(fpath)
        if stats:
            result['files'] += 1
            result['classes'] += stats.class_count
            result['functions'] += stats.function_count
            result['methods'] += stats.method_count
    return result

def print_stats(label, stats):
    if stats['files'] == 0:
        print(f"\n{label}：没有统计到任何 .py 文件（或被全部跳过）")
        return
    print(f"\n{label}")
    print(f"  文件数        : {stats['files']}")
    print(f"  类总数        : {stats['classes']}")
    print(f"  顶层函数总数  : {stats['functions']}")
    print(f"  类内方法总数  : {stats['methods']}")
    print(f"  函数合计      : {stats['functions'] + stats['methods']}")
    print(f"  总计(类+函数) : {stats['classes'] + stats['functions'] + stats['methods']}")

def main():
    parser = argparse.ArgumentParser(description='统计 Python 项目的类、函数和方法数量（自动跳过所有 >50MB 的文件和 runtime 目录）')
    parser.add_argument('root', nargs='?', default='.',
                        help='项目根目录（默认为当前目录）')
    parser.add_argument('--special', '-s', metavar='DIR',
                        help='需要单独统计的子目录名（相对于 root）')
    args = parser.parse_args()

    root = args.root
    special = args.special

    # ===== 在这里添加了 'runtime' =====
    ignore_dirs = {'.git', '__pycache__', 'venv', 'env', 'node_modules', '.idea', 'dist', 'build', 'runtime'}
    # ================================

    all_files = []
    special_files = []
    special_rel_path = special.replace('\\', os.sep).replace('/', os.sep) if special else None

    for dirpath, dirnames, filenames in os.walk(root):
        # 过滤忽略目录（包括 runtime）
        dirnames[:] = [d for d in dirnames if d not in ignore_dirs]

        for fname in filenames:
            full_path = os.path.join(dirpath, fname)

            # 全局大小检查：跳过所有 >50MB 的文件
            try:
                file_size = os.path.getsize(full_path)
                if file_size > MAX_FILE_SIZE:
                    print(f"⏭️ 跳过超大文件（>50MB）：{full_path} ({file_size / (1024*1024):.1f} MB)")
                    continue
            except OSError:
                print(f"⚠️ 无法获取文件大小，跳过：{full_path}")
                continue

            # 只处理 .py 文件
            if not fname.endswith('.py'):
                continue

            all_files.append(full_path)

            if special:
                rel = os.path.relpath(full_path, root)
                if rel.startswith(special_rel_path + os.sep) or rel == special_rel_path:
                    special_files.append(full_path)

    total_stats = collect_stats(all_files)
    special_stats = collect_stats(special_files) if special else None
    other_files = [f for f in all_files if f not in special_files]
    other_stats = collect_stats(other_files) if special else None

    print_stats("【整体项目】", total_stats)
    if special:
        print_stats(f"【特殊目录 '{special}'】", special_stats)
        print_stats("【除特殊目录外的其他部分】", other_stats)

if __name__ == '__main__':
    main()