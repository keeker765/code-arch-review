/**
 * 入口:把一批 JS/TS 源码翻成事实模型 JSON。
 *
 * 为什么不在 Python 里数括号:`//` 会出现在字符串、模板串与正则里;对象字面量、
 * 模板插值、解构都会让括号深度失真;而 `function f(){} function f(){}` 这种**静默
 * 后者胜出**只有真解析才看得见(见 references/languages.md 的 JS/TS 一节)。
 *
 * 一次进程处理**整批**文件:node 启动本机要 50~200 ms,逐文件起进程等于把扫描时间
 * 全花在启动上。路径从 stdin 读(命令行有长度上限),结果 JSON 从 stdout 出。
 *
 * 用法:`node js_probe.mjs <typescript 包目录> < paths.json`
 * 输出:`{"results": [<一个文件的全部事实> | {"path": ..., "error": ...}]}`
 */
import { readFileSync } from 'node:fs';

import { ts, extOf, scriptKindOf } from './js_ts.mjs';
import {
  lineStartsOf, collectComments, countLines, commentRowsOf, rowsOfRanges,
  withoutRows, wholeLineRowsOf, moduleDocOf, leadingRanges,
} from './js_source.mjs';
import { collectFunctions } from './js_functions.mjs';
import {
  collectConditions, collectLoops, collectThrows, collectFields,
  collectAssigns, collectReturns, collectSilentCatches, collectBindings,
} from './js_shapes.mjs';
import { collectFlatRuns, collectLayoutGaps } from './js_layout.mjs';

/**
 * 把一个文件解析成事实模型对象;解析器自身出错由调用方记进 error 字段。
 *
 * 这里只做「起手、摆好上下文、把各层的采集结果拼起来」——具体每一类事实怎么数
 * 归各自的模块。摆在这里的只有两件必须一起做的事:上下文(`ctx`)的建立,
 * 以及**整行注释的两份口径**(见下)。
 *
 * @param {string} path 文件路径。
 * @returns {object} 一个文件的全部事实。
 */
export function analyze(path) {
  const ext = extOf(path);    // 后面按扩展名判脚本种类与是不是 TS
  const text = readFileSync(path, 'utf8').replace(/^﻿/, '');    // 去掉 BOM,它会让第一列偏移整体错位
  const sf = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, scriptKindOf(ext));    // 只 parse,不 typecheck
  const ctx = {
    sf,
    text,
    isTypeScript: ext === '.ts' || ext === '.mts' || ext === '.cts' || ext === '.tsx',
  };
  ctx.starts = lineStartsOf(ctx);
  // 先把注释区间与函数事实收齐:下面两份整行注释口径都要用它们的结果
  const ranges = collectComments(ctx);    // 全部注释区间,按偏移有序
  const collected = collectFunctions(ctx);    // 函数事实,外加「文档区间」与「已认领节点」
  const allWhole = wholeLineRowsOf(ctx, ranges);    // 整行注释的全量
  // 头一行注释到哪由 headRowOf 说了算,所以整行注释的**全量**另存一份;facts 里那一份
  // 把函数文档与模块文档剔掉 —— 它们已经由 fn.doc / module_doc 计过一次数了
  ctx.docHeadRows = allWhole;
  ctx.wholeRows = withoutRows(allWhole, rowsOfRanges(ctx, [...collected.docRanges, ...leadingRanges(ctx)]));
  return {
    path,
    total_lines: countLines(ctx),
    comment_rows: [...commentRowsOf(ctx, ranges)],
    whole_line_rows: [...ctx.wholeRows],
    module_doc: moduleDocOf(ctx),
    functions: collected.facts,
    conditions: collectConditions(ctx),
    loops: collectLoops(ctx),
    raises: collectThrows(ctx),
    fields: collectFields(ctx, collected.claimed),
    assigns: collectAssigns(ctx),
    returns: collectReturns(ctx),
    silent_except_lines: collectSilentCatches(ctx),
    bindings: collectBindings(ctx),
    flat_runs: collectFlatRuns(ctx),
    layout_gaps: collectLayoutGaps(ctx),
  };
}

/**
 * 逐个文件解析,单个文件失败只标错这一个,不拖掉整批。
 *
 * 单个文件的失败**不能静默**:报错写进这一条结果的 `path`/`error` 字段,
 * 由 Python 侧决定是跳过还是整批失败 —— 一个读不动的文件不该让其余几十个白扫。
 */
function main() {
  const input = JSON.parse(readFileSync(0, 'utf8'));    // 路径列表从 stdin 来
  const results = input.map((path) => {    // 逐条转成结果,顺序与入参一致
    try {
      return analyze(path);    // 正常路径:这个文件的事实
    } catch (error) {
      // 解析器自己出错:只标这一个文件,消息原文带上便于定位
      return {path, error: String((error && error.message) || error)};
    }
  });
  process.stdout.write(JSON.stringify({results}));
}

main();
