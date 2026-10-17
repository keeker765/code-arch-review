"""`--fix` 的输入:导入顺序故意写反。

ruff 的 isort 规则应当把它排成 collections.abc → pathlib → sys。
"""
import sys
from pathlib import Path
from collections.abc import Iterable
