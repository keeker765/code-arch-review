/**
 * TypeScript 编译器的加载口 —— 整个后端只有这一处 `require`。
 *
 * 每个模块都从本文件取 `ts`,而不是各自 createRequire:包路径由命令行给一次就够,
 * 多份 require 变量只会让「编译器在哪」这件事散在七个文件里,而它本该只有一个答案。
 *
 * 为什么要 createRequire:`typescript` 是 CommonJS 包,而本目录是 ESM(`.mjs`),
 * ESM 里没有裸 `require`;它的打包入口是 `lib/typescript.js`,只有 require 拿得到导出表。
 *
 * 用法:`node js_probe.mjs <typescript 包目录> < paths.json`
 */
import { createRequire } from 'node:module';

/** `core/rules.py` 收到 flat_runs 就无条件记一条违规,所以「连续多长算平铺」只能由后端截断。 */
export const MAX_FLAT = 10;

/** 定义之间的空行数:JS 顶层与类内都是 1 行(Python 是顶层 2 行、类内 1 行)。 */
export const LAYOUT_NEED = 1;

/**
 * 扩展名 → TS 的 ScriptKind。
 *
 * `.js` / `.mjs` / `.cjs` 走 JSX 变体:同一份源码里带不带 JSX 都能解析,而 `<` 只在
 * 「表达式起始位置」才被当 JSX 标签,`a < b` 仍是二元运算。反过来只按 TS 解析,
 * 含 JSX 的 `.js` 会整片报语法错 —— 那是把可解析的文件判成解析不了。
 */
export const SCRIPT_KINDS = {
  '.ts': 'TS', '.mts': 'TS', '.cts': 'TS', '.tsx': 'TSX',
  '.jsx': 'JSX', '.js': 'JSX', '.mjs': 'JSX', '.cjs': 'JSX',
};

/** 命令行第二个参数是 typescript 包的目录或入口文件;探测哪个包可用由 Python 侧负责。 */
const requireFromHere = createRequire(import.meta.url);

/** 全进程共享的 TS 命名空间;装载失败就让异常抛出,上层据此判定这台机器走不了精确档。 */
export const ts = requireFromHere(process.argv[2]);

/** 文件扩展名(小写,含点)。 */
export function extOf(path) {
  // 没有点就是没有扩展名,给空串,让 scriptKindOf 把它退给 TS 自己按文件名推
  const cut = path.lastIndexOf('.');
  return cut < 0 ? '' : path.slice(cut).toLowerCase();    // 带上点一起小写,后面按 '.ts' 这种键查表
}

/** 一套脚本种类映射成 TS 的 ScriptKind;不认识的扩展名交给 TS 自己按文件名推。 */
export function scriptKindOf(ext) {
  const name = SCRIPT_KINDS[ext];
  // 表里没有的扩展名返回 undefined —— TS 拿 undefined 会退回按文件名判断,不是报错
  return name ? ts.ScriptKind[name] : undefined;
}
