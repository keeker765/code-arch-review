"""各语言后端:把源码解析成 `core.model.FileFacts`。

**后端不做任何阈值判断** —— 阈值集中在 `core.rules.Thresholds`,按语言给值的那份表
在 `lang.registry`。换语言只换语法翻译,不换规则。

每种语言一个包(或一个模块),入口一律暴露 `parse` / `parse_many`:

* **精确档** —— `lang.python`(stdlib `ast`)、`lang.powershell`(系统自带 AST 解析器,
  走 `pwsh` 子进程)、`lang.css`(手写 tokenizer,无依赖)
* **半精确档** —— `lang.javascript`(走 `node` 的 TypeScript 编译器;拿不到 typescript
  包时降级纯 Python 启发式并置 `heuristic=True`)
* **最低档** —— `lang.shell`(无可行解析器,纯行级启发式)

入口的模块名写在 `lang/registry.py` 的 `LANGUAGES` 里,由它延迟导入 ——
缺 `node` 或 `pwsh` 的机器上,那一门语言被跳过并说明原因,而不是让整条闸起不来。
"""
