/**
 * 段落形状:函数体里的平铺段,与定义之间的空行。
 *
 * 这两项量的是**读者扫过文件时的落脚点**,不是语法结构:
 *
 * * `flat_runs` 是「连续一长串语句、中间一行整行注释都没有」的段 —— 平铺代码没有结构提示。
 * * `layout_gaps` 是定义之间的空行 —— 删空行能把行数压到 `long-module` 阈值以下,
 *   所以必须有一条规则专门看着它,否则行数上限等于没有。
 *
 * 阈值(`MAX_FLAT` / `LAYOUT_NEED`)在这里按栈的规矩截断:规则引擎收到 `flat_runs`
 * 不问长短就记违规,所以「连续多长才算长」的判断只能由后端做,且要与
 * `core/rules.py` 的 `Thresholds.max_flat` 保持一致。
 */
import { ts, MAX_FLAT, LAYOUT_NEED } from './js_ts.mjs';
import { lineOf, contentSpan } from './js_source.mjs';
import { isFunctionNode, isClassNode, classMembersOf, nameText, addsDepth } from './js_nodes.mjs';
import { walkAll, unwrapExport } from './js_shapes.mjs';

/* ------------------------------------------------------------------ 平铺段 */

/**
 * 函数体内「连续一长串语句、中间一行整行注释都没有」的段。
 *
 * 每个段只出一条:规则的说明是「这一段没有落脚点」,同一段报 N 次只是同一个问题数 N 遍。
 *
 * @param {object} ctx 解析上下文。
 * @returns {Array<number[]>} 每项是 `[首行, 段长]`。
 */
export function collectFlatRuns(ctx) {
  const runs = new Map();    // 键是段首行,值是 [首行, 段长]
  // 逐个函数体扫描;类体与模块顶层不查,它们没有「一串语句」
  for (const fn of collectFunctionNodes(ctx)) {
    // 一个函数里可能有多个语句块(if 体、循环体、case 分支)
    for (const block of blocksOf(fn)) {
      scanBlock(ctx, block, runs);
    }
  }
  return [...runs.values()];
}

/**
 * 一个块里逐条语句扫描,控制流语句切断当前段。
 *
 * 「切断」而不是「跳过」:控制流语句自带结构提示,它上面那一串已经结束了,
 * 把它下面的语句接着算进同一段,会让两段各自的长度都不准。
 *
 * @param {object} ctx 解析上下文。
 * @param {object[]} statements 一个语句块。
 * @param {Map} runs 已记下的段(键是段首行)。
 */
export function scanBlock(ctx, statements, runs) {
  let run = [];
  // 逐条语句累计长度
  for (const statement of statements) {
    // 控制流语句自带结构提示,不算平铺,并且把当前段切断
    if (isStructural(statement)) {
      run = [];
      continue;
    }
    const row = lineOf(ctx, statement.getStart());    // 这条语句所在行
    // 段内出现独立整行注释 ⇒ 这段已被说明,重新起算
    if (
      // 上一行是整行注释
      ctx.wholeRows.has(row - 1) ||
      // 或这一行本身就是整行注释
      ctx.wholeRows.has(row)
    ) {
      run = [statement];
      continue;
    }
    run.push(statement);
    // 只有超过阈值才记:规则引擎拿到就无条件记一条,截断必须在这里做
    if (run.length > MAX_FLAT) rememberRun(ctx, runs, run, row);
  }
}

/**
 * 记下这个平铺段(同一段只留一条,长度取最终值)。
 *
 * 「取最终值」是必要的:一段有多长只有扫完才知道,而每一次越过阈值都会调到这里,
 * 保留更长的那个才不会把一段 12 行的平铺报成 6 行。
 *
 * @param {object} ctx 解析上下文。
 * @param {Map} runs 已记下的段。
 * @param {object[]} run 当前段。
 * @param {number} row 触发时的行号(段首行由 `run[0]` 给出,这里只为调用点可读)。
 */
export function rememberRun(ctx, runs, run, row) {
  const key = lineOf(ctx, run[0].getStart());    // 段首行就是这条段的身份
  const existing = runs.get(key);    // 同一个段上一次记下的长度
  // 已经记过更长的就不用改
  if (
    // 之前记过这个段
    existing &&
    // 且不比现在短
    existing[1] >= run.length
  ) return;
  runs.set(key, [key, run.length]);
}

/**
 * 控制流语句自带结构提示,不算平铺,并且切断当前段。
 *
 * @param {object} node 语句节点。
 * @returns {boolean} 算结构语句给 true。
 */
export function isStructural(node) {
  // 四种节点自带结构提示:控制流、块、函数声明、类声明
  return addsDepth(node, false)
    || ts.isBlock(node)
    || ts.isFunctionDeclaration(node)
    || ts.isClassDeclaration(node);    // 四种自带结构提示的节点
}

/**
 * 函数体内的全部语句块(含 if/else、循环体、try/catch/finally、switch 各分支)。
 *
 * 逐层找而不是只看函数体的第一层:平铺段讲的是「这一段读下来没有落脚点」,
 * 而 `if` 里面的十行连续赋值与函数体顶层的十行连续赋值是同一种问题。
 *
 * @param {object} node 函数节点。
 * @returns {object[][]} 语句块列表。
 */
export function blocksOf(node) {
  const blocks = [];
  // 函数体本身是第一段
  if (
    // 有体
    node.body &&
    // 且体里有语句
    node.body.statements
  ) pushBlock(node.body.statements, blocks);
  // 再往里找嵌套的块;平铺段讲的是读者有没有落脚点,所以逐层都要看
  if (node.body) collectBlocks(node, node.body, blocks);
  return blocks;
}

/**
 * 收一个非空语句列表。
 *
 * 空块要挡掉:它没有「一串语句」,收进去会在报告里多出一条毫无内容的段。
 *
 * @param {object[]} list 语句列表。
 * @param {object[][]} blocks 结果累积数组。
 */
function pushBlock(list, blocks) {
  // 列表存在且非空才算一段
  if (
    // 列表存在
    list &&
    // 且非空
    list.length
  ) blocks.push(list);
}

/**
 * 深度优先找块,遇到嵌套函数就停。
 *
 * switch 的每个分支单独收:分支之间可能隔着几十行,合起来算一段没有意义。
 *
 * @param {object} owner 本次扫描的函数节点。
 * @param {object} child 当前节点。
 * @param {object[][]} blocks 结果累积数组。
 */
function collectBlocks(owner, child, blocks) {
  // 嵌套函数自成一个契约,它的语句不算外层的平铺段
  if (
    // 不是本次扫描的函数
    child !== owner &&
    // 而是一个函数节点
    isFunctionNode(child)
  ) return;
  // 块体是一段
  if (ts.isBlock(child)) pushBlock(child.statements, blocks);
  // 模块块(TS 的 `declare module`)同样是一段
  if (ts.isModuleBlock(child)) pushBlock(child.statements, blocks);
  // switch 的每个分支各是一段
  if (ts.isCaseClause(child)) pushBlock(child.statements, blocks);
  // default 分支同理
  if (ts.isDefaultClause(child)) pushBlock(child.statements, blocks);
  ts.forEachChild(child, (next) => collectBlocks(owner, next, blocks));
}

/**
 * 全部函数节点(不含类体),平铺段只对函数体有意义。
 *
 * 类体被排除是因为类成员之间已经有 `packed-layout` 在管空行,再叠一条平铺段
 * 只会让同一处代码被两条规则各报一次。
 *
 * @param {object} ctx 解析上下文。
 * @returns {object[]} 函数节点列表。
 */
export function collectFunctionNodes(ctx) {
  const found = [];
  walkAll(ctx, (node) => {
    // 只收带体的函数节点;类体不是语句序列
    if (isFunctionNode(node)) found.push(node);
  });
  return found;
}

/* ------------------------------------------------------------------ 空行 */

/**
 * 顶层与类内定义之间的空行。JS 约定都是 1 行(见 SKILL.md 档位表)。
 *
 * 只查「定义」(函数/类/接口/类型/枚举),不查 `const` 块 —— 连续几行 const
 * 本来就是一段,不是两个要跳转的定义。
 *
 * @param {object} ctx 解析上下文。
 * @returns {Array<Array>} 每项是 `[行号, 名字, 实际空行数, 需要的空行数]`。
 */
export function collectLayoutGaps(ctx) {
  const gaps = [];
  checkLayout(ctx, ctx.sf.statements, gaps);
  walkAll(ctx, (node) => {
    // 类内成员之间同样要有空行
    if (isClassNode(node)) checkLayout(ctx, classMembersOf(node), gaps);
  });
  return gaps;
}

/**
 * 一个块里逐个定义查空行;块内第一个定义由外层负责,不在这里报。
 *
 * 第一个定义不报,是因为它上方的空行属于「这个块与外层之间」的间距,
 * 而那一段由外层的调用去量 —— 两边都报会让同一个空行缺口出现两条违规。
 *
 * @param {object} ctx 解析上下文。
 * @param {object[]} items 语句或成员列表。
 * @param {Array} gaps 结果累积数组。
 */
export function checkLayout(ctx, items, gaps) {
  let seen = false;
  // 逐个定义查空行
  for (const item of items) {
    // 不是定义(表达式语句、import 等)不参与
    if (!isDefinition(item)) continue;
    // 块里的第一个定义上方有多少空行由外层管,这里不报
    if (!seen) {
      seen = true;
      continue;
    }
    const row = headRowOf(ctx, item);    // 定义首行(含上方紧贴的注释)
    let got = 0;
    // 往上数空行,数够就停
    while (got < LAYOUT_NEED && isBlankRow(ctx, row - 1 - got)) got += 1;
    // 空行不够就报一条
    if (got < LAYOUT_NEED) gaps.push([row, displayNameOf(item), got, LAYOUT_NEED]);
  }
}

/**
 * 定义节点:函数 / 类 / 接口 / 类型别名 / 枚举(`export` 外壳脱掉后再判)。
 *
 * 只收这五种:`const` 语句不参与,连续几行 const 本来就是一段,
 * 拿它们要求空行会把模块顶部的常量区拆成一条条互不相关的定义。
 *
 * @param {object} node 语句节点。
 * @returns {boolean} 是定义给 true。
 */
export function isDefinition(node) {
  const inner = unwrapExport(node);    // export 包一层就先脱掉
  // 五种定义:函数、类、接口、类型别名、枚举
  return ts.isFunctionDeclaration(inner)
    || ts.isClassDeclaration(inner)
    || ts.isInterfaceDeclaration(inner)
    || ts.isTypeAliasDeclaration(inner)
    || ts.isEnumDeclaration(inner);
}

/**
 * 定义名(报告里显示用);匿名默认导出退化成关键字。
 *
 * @param {object} node 定义节点。
 * @returns {string} 显示名。
 */
export function displayNameOf(node) {
  const inner = unwrapExport(node);    // 先脱掉 export 外壳
  return nameText(inner.name) || 'default';    // 没有名字就报 default
}

/**
 * 定义的首行:上方紧贴的整行注释(含文档块)属于这个定义,空行要在它们之前。
 *
 * 不这么算的话,给一个定义补上 JSDoc 就会让它的空行数凭空少一行 ——
 * 那等于「写文档会被闸罚」,是反的。
 *
 * @param {object} ctx 解析上下文。
 * @param {object} node 定义节点。
 * @returns {number} 1 基行号。
 */
export function headRowOf(ctx, node) {
  let row = lineOf(ctx, node.getStart());    // 从定义自己那一行起,再往上找注释
  // 上方紧贴的整行注释属于这个定义,一路往上找
  while (
    // 还没到文件头
    row > 1 &&
    // 且上一行是整行注释
    ctx.docHeadRows.has(row - 1)
  ) row -= 1;
  return row;
}

/**
 * 这一行是不是空的。越界(文件头之上)当作已满足。
 *
 * @param {object} ctx 解析上下文。
 * @param {number} row 1 基行号。
 * @returns {boolean} 空行给 true。
 */
export function isBlankRow(ctx, row) {
  // 文件头之上没有行,当作已满足,否则每个文件的第一段都会报
  if (row < 1) return true;
  const span = contentSpan(ctx, row);    // 没有内容区间就是空行
  return span === null;    // 没有内容区间就是空行
}
