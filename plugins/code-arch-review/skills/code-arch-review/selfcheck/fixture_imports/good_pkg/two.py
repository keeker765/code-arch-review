import sys


def probe():
    """返回一个与导入顺序无关的值。"""
    return sys.version_info[0]
