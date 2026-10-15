/**
 * 源码文本层:偏移 → 行列、注释区间、文档正文。
 *
 * 这一层只回答「一段字符在这份文本的哪里」,不碰 AST 的形状 —— 判断一个节点是什么
 * (函数、类、赋值)是 `js_nodes` 与 `js_functions` 的事。分开是因为注释与文档恰恰
 * **不属于任何节点**:`}` 与 `else` 之间的那行注释只存在于两个 token 的缝里,
 * 而「缝里有什么」和「节点是什么」是两种不同的问题,混在一起会两边都看不清。
 *
 * 全部行号取自 TS 自己的行表,不自己按 `\n` 切:JS 认 U+2028 / U+2029 为行终止符
 * (它们可以合法地出现在字符串里),自己数会静默错位,而错位的行号指向别的行。
 */
import { ts } from './js_ts.mjs';

/**
 * 每一行的起始偏移,下标是 0 基行号。
 *
 * 单独包一层是为了让「行号从哪来」只有一个答案:后面的 `lineOf`、`contentSpan`、
 * `countLines` 全部落在这张表上,谁都不许自己数换行符。
 *
 * @param {object} ctx 一次解析的上下文,含源码文本与 SourceFile。
 * @returns {number[]} 每行首字符的偏移数组。
 */
export function lineStartsOf(ctx) {
  return ctx.sf.getLineStarts();    // 与 getLineAndCharacterOfPosition 同一张表,不再自己数换行
}

/**
 * 这个位置的字符是不是行终止符。JS 认四种:`\n`、`\r` 与两个 Unicode 行分隔符。
 *
 * @param {string} text 源码文本。
 * @param {number} index 待判字符的偏移。
 * @returns {boolean} 是行终止符给 true。
 */
export function isLineBreakAt(text, index) {
  const code = text.charCodeAt(index);    // 判码点比逐字符比较省一份表
  return code === 10 || code === 13 || code === 0x2028 || code === 0x2029;    // 四种终止符一次判完
}

/**
 * 这个字符算不算行内空白。行终止符也算 —— 拼在行尾时要先摘掉。
 *
 * 行终止符之所以按空白算,是因为 `contentSpan` 要拿它去切行尾:CR 与两个 Unicode
 * 分隔符都可能是这一行的最后一个「看不见的字符」,不摘掉就会把行尾判在别处。
 *
 * @param {string} ch 单个字符。
 * @returns {boolean} 算空白给 true。
 */
export function isInlineSpace(ch) {
  const code = ch.charCodeAt(0);    // 先取码点,后面按数值判那两个 Unicode 分隔符
  // 四种行内空白一个一个写出来,不与任何简写混用 —— 别的空白字符不该在这里被放行
  if (
    // 空格:最常见的一种
    ch === ' ' ||
    // 制表符:对齐缩进留下的
    ch === '\t' ||
    // 换页符:少数编辑器仍会插
    ch === '\f' ||
    // 纵向制表符:同上,更少见
    ch === '\v'
  ) return true;
  // \r 与两个 Unicode 分隔符按行内空白处理:它们能被合法地塞在字符串里,是行内噪声
  return code === 13 || code === 0x2028 || code === 0x2029;
}

/**
 * 某个偏移所在的行号,1 基。
 *
 * @param {object} ctx 解析上下文。
 * @param {number} pos 字符偏移。
 * @returns {number} 1 基行号。
 */
export function lineOf(ctx, pos) {
  return ctx.sf.getLineAndCharacterOfPosition(pos).line + 1;    // 报告里的行号都从这里出去,1 基只换算这一次
}

/**
 * 文件总行数。
 *
 * 与行号同一套口径(TS 的行表),末尾那个换行不额外算一行 —— 否则每个以换行结尾的
 * 文件都会凭空多一行,而 `long-module` 正是拿这个数与 500 比。
 *
 * @param {object} ctx 解析上下文。
 * @returns {number} 物理行数。
 */
export function countLines(ctx) {
  const last = ctx.text.length - 1;    // 最后一个字符的偏移
  // 空文件没有最后一行,给 0 而不是 1
  if (last < 0) return 0;
  // 结尾是换行符时 TS 会为「换行之后」额外记一个行首,减掉它才是真实行数
  return isLineBreakAt(ctx.text, last) ? ctx.starts.length - 1 : ctx.starts.length;
}

/* ------------------------------------------------------------------ 注释与文档 */

/**
 * 收集全部注释区间。
 *
 * 两个坑都在这里绕开了:
 *
 * 1. **不能只遍历节点**。`ts.forEachChild` 只走 AST 节点,而注释常常夹在两个同级
 *    token 之间 —— `}` 与 `else` 之间的那行注释不属于任何节点,只按节点扫会漏掉它,
 *    于是 `else if` 会被误报成「上方缺独立注释」。`getChildren()` 会把 token 也当
 *    子节点给出,夹缝因此被覆盖。
 * 2. **不能用裸 scanner**。scanner 不知道 JSX 上下文,`<div>https://x</div>` 里的
 *    `//` 会被当成行注释;AST 的 trivia 是解析器判定的,不会认错。
 *
 * @param {object} ctx 解析上下文。
 * @returns {object[]} 按偏移排序的注释区间(含 pos 与 end)。
 */
export function collectComments(ctx) {
  const seen = new Map();    // 键是「起点:终点」,同一个注释会被两个节点各报一次

  /** 收一个区间并按位置去重 —— 它同时是前一个节点的行尾与后一个节点的行首。 */
  function put(range) {
    // 没有注释时 getLeadingCommentRanges 给 undefined,这里跳过
    if (range) seen.set(`${range.pos}:${range.end}`, range);
  }

  /** 深度优先走整棵树,**带 token**:缝里的注释只有 token 认得。 */
  function visit(node) {
    // 本节点的前导注释
    for (const range of ts.getLeadingCommentRanges(ctx.text, node.getFullStart()) || []) put(range);
    // 本节点同一行上的行尾注释
    for (const range of ts.getTrailingCommentRanges(ctx.text, node.getEnd()) || []) put(range);
    // 递归到子节点与 token
    for (const child of node.getChildren(ctx.sf)) visit(child);
  }

  visit(ctx.sf);
  // 按偏移排序:后面按行号滚动匹配时依赖「区间有序」这个前提
  return [...seen.values()].sort((left, right) => left.pos - right.pos);
}

/**
 * 出现过注释的行号集合(**含行尾注释**)。覆盖率的行尾判据用它。
 *
 * 与 `wholeLineRowsOf` 的区别是这里的「含」:行尾注释也算这一行有注释,因为
 * 赋值与 return 这类一行放得下的构造接受行尾注释。
 *
 * @param {object} ctx 解析上下文。
 * @param {object[]} ranges 注释区间。
 * @returns {Set<number>} 行号集合。
 */
export function commentRowsOf(ctx, ranges) {
  const rows = new Set();    // 行号天然去重:同一行有两条注释也只算一行
  // 逐条注释展开成它覆盖的每一行
  for (const range of ranges) {
    const first = lineOf(ctx, range.pos);    // 注释起点所在行
    const last = lineOf(ctx, range.end);     // 注释终点所在行
    // 块注释跨的每一行都算「这一行有注释」
    for (let row = first; row <= last; row += 1) rows.add(row);
  }
  return rows;
}

/**
 * 若干注释区间覆盖到的全部行号。
 *
 * 与 `commentRowsOf` 算出来的是同一件事,分成两个函数是因为调用方的意图不同:
 * 一个要判「这一行有没有注释」,一个要按区间集合去剔行。合并会让两边的语义互相污染。
 *
 * @param {object} ctx 解析上下文。
 * @param {object[]} ranges 注释区间。
 * @returns {Set<number>} 行号集合。
 */
export function rowsOfRanges(ctx, ranges) {
  const rows = new Set();    // 与 commentRowsOf 分开写,因为两者的含义不同,不该互相借用
  // 逐条注释展开成它覆盖的每一行
  for (const range of ranges) {
    const first = lineOf(ctx, range.pos);    // 注释起点所在行
    const last = lineOf(ctx, range.end);     // 注释终点所在行
    // 块注释跨的每一行都算
    for (let row = first; row <= last; row += 1) rows.add(row);
  }
  return rows;
}

/**
 * left 里有、drop 里没有的那些行。
 *
 * 模块文档与函数文档已经从事实里单独计过数,再留在整行注释集合里会让同一份文档
 * 进覆盖率两次,所以这里把它们的行剔出去。
 *
 * @param {Set<number>} left 全量行号。
 * @param {Set<number>} drop 要剔掉的行号。
 * @returns {Set<number>} 剩下的行号。
 */
export function withoutRows(left, drop) {
  const kept = new Set();    // 留下的行号,新集合而不是原地删 —— left 还要被别处用
  // 逐行筛,行号集合很小,可读性优先于集合运算
  for (const row of left) {
    // 命中要丢掉的行就跳过
    if (drop.has(row)) continue;
    kept.add(row);
  }
  return kept;
}

/**
 * 该行去掉首尾空白后的内容区间;空行返回 null。
 *
 * 返回的是**偏移**而不是字符串:调用方要拿它去和注释区间的起止比大小,
 * 一旦在这里切成字符串,后面就得再算一次偏移,多一次出错的机会。
 *
 * @param {object} ctx 解析上下文。
 * @param {number} row 1 基行号。
 * @returns {{head: number, tail: number}|null} 内容区间;空行或越界给 null。
 */
export function contentSpan(ctx, row) {
  const start = ctx.starts[row - 1];
  // 越界行(文件头之上)当作没有内容
  if (start === undefined) return null;
  const end = ctx.starts[row] === undefined ? ctx.text.length : ctx.starts[row] - 1;    // 下一行行首之前一格
  let head = start;
  // 吃掉行首空白,head 指向第一个非空白字符
  while (head < end && isInlineSpace(ctx.text[head])) head += 1;
  let tail = end;
  // 从行尾往回收,tail 指向最后一个非空白字符之后
  while (tail > head && isInlineSpace(ctx.text[tail - 1])) tail -= 1;
  return tail <= head ? null : {head, tail};    // 全是空白就是空行
}

/**
 * **独立整行**注释所在的行号集合:整行内容都落在一个注释块里。
 *
 * 判据是「整行内容被注释覆盖」而不是「以 // 开头」—— 块注释的中间行
 * (` * 说明`)也必须是整行注释,否则多行 JSDoc 只有第一行算数。
 *
 * @param {object} ctx 解析上下文。
 * @param {object[]} ranges 注释区间(必须按偏移有序)。
 * @returns {Set<number>} 整行注释所在的行号。
 */
export function wholeLineRowsOf(ctx, ranges) {
  const rows = new Set();    // 整行注释所在的行号
  let cursor = 0;
  const total = countLines(ctx);    // 走完整个文件,末尾的换行不算一行
  // 逐行判断:一行算整行注释,当且仅当它的全部内容落在同一个注释区间里
  for (let row = 1; row <= total; row += 1) {
    const span = contentSpan(ctx, row);    // 本行的内容区间,空行给 null
    // 空行没有内容,谈不上是不是注释
    if (!span) continue;
    // 跳过已经结束的区间:ranges 按偏移有序,游标不必回退
    while (cursor < ranges.length && ranges[cursor].end <= span.head) cursor += 1;
    const range = ranges[cursor];
    // 行首、行尾都落在同一个区间内才算整行注释(只盖住一半的是「代码后面跟注释」)
    if (
      // 游标后面还有区间
      range &&
      // 区间起点不晚于行首
      range.pos <= span.head &&
      // 区间终点不早于行尾
      range.end >= span.tail
    ) rows.add(row);
  }
  return rows;
}

/**
 * 去掉注释定界符与每行行首那颗星之后的正文。
 *
 * 摘的是**装饰**不是内容:`*` 与 `//` 只是排版,读者要的是后面那句话。
 * 只去行首那一颗星,行内的 `*`(比如 `a * b`)必须原样留着。
 *
 * @param {string} raw 注释原文(含定界符)。
 * @returns {string} 正文。
 */
export function stripCommentMarkers(raw) {
  const body = raw.replace(/^\/\*\*?/, '').replace(/\*\/$/, '').replace(/^\/\//, '');    // 两端定界符都摘掉,// 与 /* */ 同样处理
  const lines = body.split('\n').map((line, index) => {    // 逐行摘掉行首装饰
    // 第一行没有行首装饰,但可能有定界符留下的一个空格;其余行要去掉行首那颗星
    const cleaned = index === 0 ? line.trimStart() : line.replace(/^\s*\*\s?/, '');
    return cleaned.replace(/\s+$/, '');    // 去掉行尾空白
  });
  return lines.join('\n').replace(/^\n+/, '').replace(/\n+$/, '');    // 定界符占的两端空行是格式不是正文
}

/**
 * 文件开头那一串注释区间 —— 模块文档的候选。
 *
 * @param {object} ctx 解析上下文。
 * @returns {object[]} 文件头注释区间。
 */
export function leadingRanges(ctx) {
  return ts.getLeadingCommentRanges(ctx.text, 0) || [];    // 偏移 0 的前导注释就是文件头注释
}

/**
 * 文件开头的注释块 —— 模块文档在 JS 里的对应物(没有则 None)。
 *
 * 判据比函数的 JSDoc 松:它不要求 `/**` 开头,也不要求紧贴第一行代码 ——
 * 文件头的 `//` 连续注释、版权行后面隔一行再写说明,都是常见的模块文档形态。
 *
 * @param {object} ctx 解析上下文。
 * @returns {string|null} 模块说明正文;没有给 null。
 */
export function moduleDocOf(ctx) {
  const ranges = leadingRanges(ctx);    // 文件头那串注释,可能有多段
  // 文件开头没有注释就没有模块说明
  if (!ranges.length) return null;
  const texts = ranges.map((range) => stripCommentMarkers(ctx.text.slice(range.pos, range.end)));    // 每段各自摘定界符
  // 多段开头的注释拼成一份模块说明;全是空白时给 null,与「没有模块说明」同义
  return texts.join('\n').replace(/^\n+/, '').replace(/\n+$/, '') || null;
}

/**
 * 定义上方**紧贴**的 `/** ... *\/` 块所在区间;不是 JSDoc 或中间隔了空行都给 null。
 *
 * 中间隔空行就不算「紧贴」:那样的注释是文件里的段落说明,不是这个函数的契约。
 *
 * @param {object} ctx 解析上下文。
 * @param {object} node 定义节点。
 * @returns {object|null} 文档区间;没有给 null。
 */
export function jsDocRangeOf(ctx, node) {
  const ranges = ts.getLeadingCommentRanges(ctx.text, node.getFullStart()) || [];    // 节点上方紧贴的那串注释
  const last = ranges[ranges.length - 1];
  // 一个注释都没有
  if (!last) return null;
  // 只有 /** 开头才是文档注释,// 与 /* 是普通注释
  if (!ctx.text.startsWith('/**', last.pos)) return null;
  const gap = ctx.text.slice(last.end, node.getStart());    // 注释末尾到定义起点之间的原文
  // 中间出现空行就不算紧贴:它是段落说明,不是这个函数的契约
  if (/\n[^\S\n]*\n/.test(gap)) return null;
  return last;
}

/**
 * 定义上方的文档正文(调用方保证区间非空)。
 *
 * @param {object} ctx 解析上下文。
 * @param {object} range 文档区间。
 * @returns {string|null} 去掉定界符后的正文。
 */
export function jsDocTextOf(ctx, range) {
  return stripCommentMarkers(ctx.text.slice(range.pos, range.end)) || null;    // 空壳文档 `/** */` 与没有文档同义
}

/**
 * 摘要行之后、不在任何 `@标签` 行里的非空行数。
 *
 * 只数散文:小节里的 `@param` 清单是接口列表,不是「为什么这么做」的解释。
 * 一眼就能看出在做什么的小函数不需要解释段,所以这个数只与体量挂钩。
 *
 * @param {string} doc 文档正文(不含定界符)。
 * @returns {number} 解释段的行数。
 */
export function docProseLines(doc) {
  const lines = doc.split('\n').slice(1);    // 第 0 行是摘要,解释段从第 1 行起
  let prose = 0;
  let inSection = false;
  // 逐行累计:撞到第一个 @标签之后剩下的都是接口清单
  for (const line of lines) {
    const text = line.trim();    // 定界符对齐留下的缩进不算内容
    // 空行不计数,也不结束解释段
    if (!text) continue;
    // 撞到 @标签:后面全是小节内容,不再算散文
    if (/^@\w/.test(text)) {
      inSection = true;
      continue;
    }
    // 已经进入小节,再出现的非标签行也不属于「摘要之后的解释」
    if (inSection) continue;
    prose += 1;
  }
  return prose;
}

/**
 * 文档里有没有这个 JSDoc 小节(`@returns` 与 `@return` 是同一个小节)。
 *
 * @param {string} doc 文档正文(不含定界符)。
 * @param {string} section 小节名,取值 `@param` / `@returns` / `@throws`。
 * @returns {boolean} 有小节给 true。
 */
export function docHasSection(doc, section) {
  // 参数小节:JSDoc 里只有 @param 一种写法
  if (section === '@param') return /@param\b/.test(doc);
  // 返回值小节:@return 与 @returns 都合法
  if (section === '@returns') return /@returns?\b/.test(doc);
  // 其余只可能是抛异常小节:@throws 与 @exception 同义
  return /@throws?\b|@exception\b/.test(doc);
}
