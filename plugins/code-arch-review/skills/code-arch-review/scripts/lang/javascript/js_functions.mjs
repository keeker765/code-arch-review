/**
 * 函数事实:把「一个函数/类」翻译成 `FunctionFact` 的每一项。
 *
 * 这里决定三件规则引擎不判的事,每一件都直接改变报告:
 *
 * 1. **谁算公开**。匿名回调、`_` 与 `#` 开头、TS 的 `private`、对象字面量的成员都不算 ——
 *    要求给一个没有对外名字的东西写 JSDoc,只会制造噪声,而噪声多了闸就会被关掉。
 * 2. **体量怎么量**。首尾语句之间的跨度,与 Python 同口径。
 * 3. **哪些小节是必需的**。有参数要 `@param`、体里有 return 表达式要 `@returns`、
 *    有 throw 要 `@throws`;判据只认函数体自己的,不下钻嵌套函数。
 */
import { ts } from './js_ts.mjs';
import { jsDocRangeOf, jsDocTextOf, docProseLines, docHasSection, lineOf } from './js_source.mjs';
import {
  isClassNode, isScopeNode, nameText, hasPrivateModifier,
  declaredName, paramNames, startLineOf, bodyLinesOf, subtreeHas, addsDepth,
} from './js_nodes.mjs';

/**
 * 文档小节的齐全情况:有参数要 `@param`,有 return 表达式要 `@returns`,有 throw 要 `@throws`。
 *
 * 返回两个清单而不是一个布尔:报告里要写出「缺哪一个小节」,只报「缺小节」等于让
 * 作者自己回去数。没有文档时 `missing` 留空 —— 那一条由 `no-docstring` 说,
 * 同一个错报两次会让作者以为有两处要改。
 *
 * @param {object} node 函数或类节点。
 * @param {string|null} doc 文档正文。
 * @param {string[]} params 参数名列表。
 * @returns {{required: string[], missing: string[]}} 必需小节与其中缺的那些。
 */
export function sectionFacts(node, doc, params) {
  // 类只判文档:参数表与返回值小节对类不适用
  if (isClassNode(node)) return {required: [], missing: []};
  const hasReturn = subtreeHas(node.body, ts.isReturnStatement, (item) => Boolean(item.expression));    // 只认带表达式的 return
  const hasThrow = subtreeHas(node.body, ts.isThrowStatement, () => true);    // throw 语句自身就是判据
  const required = [];
  // 有参数就要写清每个参数是什么
  if (params.length) required.push('@param');
  // 有返回值就要写清调用方拿到的是什么口径
  if (hasReturn) required.push('@returns');
  // 会抛异常就要写清什么前提被破坏
  if (hasThrow) required.push('@throws');
  // 没有文档时不报缺小节 —— 那一条由 no-docstring 说,重复报等于一个错记两次
  if (!doc) return {required, missing: []};
  return {required, missing: required.filter((item) => !docHasSection(doc, item))};    // 逐个查小节在不在
}

/**
 * 控制流嵌套层数。只数 `if`/`for`/`while`/`do`/`switch`/`try`,
 * 对象字面量与模板插值不加深度;函数体自身不算一层;嵌套函数另起一个作用域。
 *
 * 「不加深度」的三种是刻意的:对象字面量与模板插值只是写法上的缩进,读者一眼能扫完,
 * 把它们算成一层会让 `deep-nesting` 去报一堆本来很扁平的数据字面量。
 *
 * 「函数体自身不算一层」是刻意的:所有函数都有的那一层不携带信息,算进去等于
 * 给每个函数白送 1,阈值就得跟着加 1,两边都不是人话。
 *
 * @param {object} node 函数节点。
 * @returns {number} 最深层数。
 */
export function nestingDepthOf(node) {
  let worst = 0;

  /**
   * 逐层下钻并累计深度。
   *
   * @param {object} child 当前节点。
   * @param {number} depth 进入这个节点前的深度。
   * @param {boolean} isElseBranch 它是不是上层 `if` 的 else 分支。
   */
  function visit(child, depth, isElseBranch) {
    // 嵌套作用域另起一层,不计入外层的深度
    if (isScopeNode(child)) return;
    const level = depth + (addsDepth(child, isElseBranch) ? 1 : 0);    // 这一层本身算不算一层
    // 记下最深的那一层
    if (level > worst) worst = level;
    ts.forEachChild(child, (next) => visit(next, level, ts.isIfStatement(child) && child.elseStatement === next));
  }

  // 函数体自身不算一层,所以从 0 起算
  if (node) ts.forEachChild(node, (child) => visit(child, 0, false));
  return worst;
}

/* ------------------------------------------------------------------ 字符串键 */

/**
 * 同一对象上用过的**不同**属性名个数里的最大值(与 Python 后端的口径一致)。
 *
 * 用户对象只在 TS 里算:纯 JS 里对象就是惯用的记录类型,查字符串键是制造噪声
 * (见 references/languages.md)。函数内部在多个对象上取键时取最大值,因为报告的
 * 单位是「这一个函数里最像接口的那个对象」。
 *
 * @param {object} node 函数节点。
 * @returns {number} 键数最大值。
 */
export function stringKeyCountOf(node) {
  const byObject = new Map();    // 键是接收者文本,值是这个对象上用过的属性名集合
  // 空节点(没有 body 的签名)直接给 0
  if (node) scanKeys(node, node, byObject);
  let worst = 0;
  // 逐个对象比键数,取最大的那个
  for (const keys of byObject.values()) {
    // 比当前最大值大就换
    if (keys.size > worst) worst = keys.size;
  }
  return worst;
}

/**
 * 在一个函数的子树里收集属性访问,按接收者归堆。
 *
 * 与 `stringKeyCountOf` 分开,是为了让后者的体量只剩「起手、取最大、收尾」三步:
 * 采集规则(认哪些形态、筛哪些接收者)挪到这里,它自己的复杂度才看得见。
 *
 * @param {object} child 当前节点。
 * @param {object} root 本次扫描的根(遇到它之外的嵌套作用域就停)。
 * @param {Map} byObject 接收者文本 → 属性名集合。
 */
function scanKeys(child, root, byObject) {
  // 嵌套作用域是另一个契约,它的键不算在外层头上
  if (
    // 不是本次扫描的根
    child !== root &&
    // 而是一个嵌套作用域
    isScopeNode(child)
  ) return;
  // `o.k` 形态:取属性名
  if (ts.isPropertyAccessExpression(child)) {
    // 只认简单接收者:链式 a.b.c 会把中间对象也算成一个「接口」
    if (isSimpleReceiver(child.expression)) addKey(byObject, child.expression.getText(), nameText(child.name));
  // `o["k"]` 形态:与属性访问分开判,因为下标要先取出再筛
  } else if (ts.isElementAccessExpression(child)) {
    const index = child.argumentExpression;
    // `o["k"]` 与 `o.k` 是同一件事,只认字符串下标
    if (
      // 下标存在
      index &&
      // 且是字符串字面量
      ts.isStringLiteral(index) &&
      // 且接收者是简单对象
      isSimpleReceiver(child.expression)
    ) addKey(byObject, child.expression.getText(), index.text);
  }
  ts.forEachChild(child, (next) => scanKeys(next, root, byObject));
}

/**
 * 给某个接收者记一个键。
 *
 * @param {Map} byObject 接收者文本 → 属性名集合。
 * @param {string} target 接收者文本。
 * @param {string} key 属性名。
 */
function addKey(byObject, target, key) {
  // 空名字(计算属性名等)不算一个键
  if (!key) return;
  // 第一次见到这个接收者时先建一个集合
  if (!byObject.has(target)) byObject.set(target, new Set());
  byObject.get(target).add(key);
}

/**
 * 接收者是不是一个「对象变量」(`o.a` / `this.a`);链式 `a.b.c` 只认最左那段。
 *
 * 不认更复杂的接收者(`f().a`、`a[0].b`)是因为那些多半是一次性的取用,
 * 把它们当成「同一个对象的多个键」会把噪声算成信号。
 *
 * @param {object} node 接收者表达式。
 * @returns {boolean} 是裸名字或 this 给 true。
 */
export function isSimpleReceiver(node) {
  return ts.isIdentifier(node) || node.kind === ts.SyntaxKind.ThisKeyword;    // 裸名字,或 this
}

/* ------------------------------------------------------------------ 函数事实 */

/**
 * 把一个函数/类节点建成一条事实。
 *
 * 类也走这条路:类与函数共用同一个事实形状,只把参数表、嵌套层数、字符串键三项
 * 归零,由规则引擎按 `is_class` 决定查不查 —— 后端不做阈值判断,它只说是什么。
 *
 * @param {object} ctx 解析上下文。
 * @param {object} node 函数或类节点。
 * @param {string} name 已归一到可读文本的名字。
 * @param {boolean} isWiring 它是不是就地接线(见 isWiring)。
 * @param {object|null} docRange 紧贴在上方的文档区间。
 * @returns {object} 一条 `FunctionFact` 形状的普通对象。
 */
export function buildFunction(ctx, node, name, isWiring, docRange) {
  const isClass = isClassNode(node);    // 类与函数共用一条事实,靠这个标记分流
  const doc = docRange ? jsDocTextOf(ctx, docRange) : null;    // 区间有才去取正文,省一次切片
  const params = isClass ? [] : paramNames(node);    // 类不填参数表,参数表是给函数用的
  const sections = sectionFacts(node, doc, params);    // 必需小节与其中缺的那些
  return {
    name,
    line: startLineOf(ctx, node),
    end_line: lineOf(ctx, node.getEnd()),
    body_lines: bodyLinesOf(ctx, node),
    params,
    is_public: isPublicName(name, node, isWiring),
    is_class: isClass,
    doc,
    required_sections: sections.required,
    missing_sections: sections.missing,
    // 纯 JS 里对象就是惯用的记录类型,查字符串键是制造噪声(见 languages.md),所以只有 TS 算
    string_key_count: ctx.isTypeScript && !isClass ? stringKeyCountOf(node) : 0,
    nesting_depth: isClass ? 0 : nestingDepthOf(node),
    doc_prose_lines: doc ? docProseLines(doc) : 0,
  };
}

/**
 * 这个名字算不算公开。
 *
 * 匿名(回调)不算:它没有对外名字,要求文档只会制造噪声。TS 的 `private`
 * 与 `#x` 也不算 —— 那不是对外接口。对象字面量的成员同样不算:
 * 它们是就地接线,不是按名字可达的模块接口。
 *
 * @param {string} name 名字。
 * @param {object} node 定义节点。
 * @param {boolean} isWiring 它是不是就地接线(见 isWiring)。
 * @returns {boolean} 公开给 true。
 */
export function isPublicName(name, node, isWiring) {
  // 匿名(回调、默认导出)没有对外名字
  if (!name) return false;
  // 下划线开头是惯例上的私有,井号开头是 ES 的私有字段
  if (
    // 惯例私有
    name.startsWith('_') ||
    // 语言级私有
    name.startsWith('#')
  ) return false;
  // TS 的 private 修饰符同样是私有
  if (hasPrivateModifier(node)) return false;
  return !isWiring;    // 就地接线的名字由别人定,不是按名字可达的模块接口
}

/* ------------------------------------------------------------------ 命名 */

/**
 * 子节点里那个「被父节点命名」的函数/类;没有就返回 null。
 *
 * `const f = () => {}` 的名字长在变量声明上,`exports.foo = function () {}` 的
 * 名字长在赋值左值上 —— 函数节点自己是无名的,所以必须回头问父节点。
 *
 * @param {object} node 父节点。
 * @returns {object|null} 被命名的函数/类节点。
 */
export function innerFunctionOf(node) {
  // 变量声明:`const f = ...`
  if (ts.isVariableDeclaration(node)) return functionLikeOrNull(node.initializer);
  // 属性赋值 `{f: ...}`
  if (ts.isPropertyAssignment(node)) return functionLikeOrNull(node.initializer);
  // 类字段 `f = ...`,与属性赋值的取法一样
  if (ts.isPropertyDeclaration(node)) return functionLikeOrNull(node.initializer);
  // 普通赋值 `exports.foo = ...`:只有 `=` 才算命名,`+=` 之类不是
  if (
    // 是二元表达式
    ts.isBinaryExpression(node) &&
    // 且运算符是等号
    node.operatorToken.kind === ts.SyntaxKind.EqualsToken
  ) {
    return functionLikeOrNull(node.right);    // 名字长在右值上
  }
  return null;
}

/**
 * 是函数/类节点就原样返回,否则 null。
 *
 * @param {object} node 任意节点,允许为 null。
 * @returns {object|null} 函数或类节点。
 */
export function functionLikeOrNull(node) {
  // 初始化式可能是字面量,那种情况不算函数定义
  if (!node) return null;
  return isScopeNode(node) ? node : null;    // 是函数或类才认
}

/**
 * 父节点给的名字:变量名、属性名,或 CommonJS 赋值右侧最后一节(`exports.foo = ...`)。
 *
 * 三种形态对应三种命名习惯,少认一种,那一类函数的 `name` 就是空串 —— 而空名字
 * 会让它从「公开接口」掉成「匿名回调」,连 JSDoc 要求一起消失,整片静默漏掉。
 *
 * @param {object} ctx 解析上下文(保留给未来需要读源码的形态)。
 * @param {object} node 父节点。
 * @returns {string} 名字;拿不到给空串。
 */
export function nameFromParent(ctx, node) {
  // 变量声明:`const f = ...` 取变量名
  if (ts.isVariableDeclaration(node)) return nameText(node.name);
  // 属性 `{f: ...}` 取属性名
  if (ts.isPropertyAssignment(node)) return nameText(node.name);
  // 类字段与属性赋值的名字同一个取法
  if (ts.isPropertyDeclaration(node)) return nameText(node.name);
  return rightmostName(node.left);    // 赋值形态取左值最后一段
}

/**
 * 赋值左侧最右边那一段名字:`exports.foo` 给 `foo`,`a.b.c` 给 `c`。
 *
 * 取最右一段是因为报告要的是「这个函数叫什么」,而不是它挂在哪个对象上:
 * `module.exports.foo` 与 `exports.foo` 是同一个函数,不该报成两个名字。
 *
 * @param {object} node 赋值左值。
 * @returns {string} 名字;拿不到给空串。
 */
export function rightmostName(node) {
  // 没有左值(解构赋值)就没有名字
  if (!node) return '';
  // 裸名字就是它自己
  if (ts.isIdentifier(node)) return node.text;
  // 属性访问取最后一段
  if (ts.isPropertyAccessExpression(node)) return nameText(node.name);
  // 字符串下标 `exports["foo"]` 取下标文本
  if (
    // 是下标访问
    ts.isElementAccessExpression(node) &&
    // 下标存在
    node.argumentExpression &&
    // 且是字符串字面量
    ts.isStringLiteral(node.argumentExpression)
  ) return node.argumentExpression.text;
  // 其余形态(解构、计算下标)拿不到名字
  return '';
}

/**
 * 这个定义是不是**就地接线**:接到一个已经存在的对象上,而不是按名字对外新增接口。
 *
 * 接到**成员表达式**上的一律算:`{f: () => {}}` 是接到对象字面量上,`el.onload = () => {}`
 * 是接到 DOM 节点上,`exports.foo = function () {}` 是接到导出对象上。三者的共同点是
 * **名字由别人定**(属性名、导出位置)或根本没有名字,作者能写的 JSDoc 只剩复述右侧那串
 * `() => {}` —— 而那正是「不许复述代码」要挡的东西。要绕开还得把代码改成
 * `addEventListener('load', ...)`,那是为过闸改行为。
 *
 * 赋给**裸名字**的(`foo = function () {}`)不算:名字是作者起的,文档有落点。
 *
 * 注意它们仍留在 `functions` 里 —— 不要求文档不等于不用量体量和嵌套,
 * 一个几百行的事件处理器照样该被 `long-function` 抓出来。
 *
 * @param {object} node 命名者节点(属性赋值、方法声明、变量声明、赋值表达式)。
 * @returns {boolean} 是就地接线给 true。
 */
export function isWiring(node) {
  // 属性赋值 `{f: function () {}}`
  if (ts.isPropertyAssignment(node)) return true;
  // 简写方法 `{f() {}}`:要看它的父节点是不是对象字面量
  if (ts.isMethodDeclaration(node)) return Boolean(node.parent && ts.isObjectLiteralExpression(node.parent));
  // 赋值表达式 `x.y = fn`:先确认它是赋值
  if (
    // 是二元表达式
    ts.isBinaryExpression(node) &&
    // 且运算符是等号 —— `+=` 与 `??=` 不产生新定义
    node.operatorToken.kind === ts.SyntaxKind.EqualsToken
  ) {
    // 左值是成员访问才算接线
    return (
      // `x.y = fn`
      ts.isPropertyAccessExpression(node.left) ||
      // `x['y'] = fn`
      ts.isElementAccessExpression(node.left)
    );
  }
  // 类方法与类字段不是接线:它们按名字挂在类上,是类对外接口的一部分
  return false;
}

/* ------------------------------------------------------------------ 采集 */

/**
 * 全部函数/类事实。父节点能给名字的(变量、属性)按父节点的名字记一次,不重复记匿名。
 *
 * 同时回报「已被父节点命名过」的节点集合与文档注释区间:前者让字段清单避开箭头函数
 * 字段(否则同一个成员会被当成方法报一次、又当成字段报一次),后者让密度统计里
 * 文档注释不会被算第二遍(它已经由 `fn.doc` 计过)。
 *
 * @param {object} ctx 解析上下文。
 * @returns {{facts: object[], claimed: Set<object>, docRanges: object[]}} 三条结果。
 */
export function collectFunctions(ctx) {
  // 三个内层函数要共享的三样东西打成一份状态,提出来才不必层层传参
  const state = {ctx, facts: [], claimed: new Set(), docRanges: []};
  visitTree(state, ctx.sf);
  return {facts: state.facts, claimed: state.claimed, docRanges: state.docRanges};
}

/**
 * 记一条函数事实,并留下它的文档区间。
 *
 * 文档要挂在**锚点**上而不是函数节点上:命名长在父节点上的那些函数
 * (`const f = () => {}`),JSDoc 写在整个声明上方,函数节点自己的前导注释里没有它。
 *
 * @param {object} state 采集状态。
 * @param {object} anchor 文档要挂在哪 —— 通常是命名者所在的那一层。
 * @param {object} node 函数或类节点。
 * @param {string} name 已归一的函数名。
 * @param {boolean} isWiring 它是不是就地接线(见 isWiring)。
 */
function addFact(state, anchor, node, name, isWiring) {
  const docRange = jsDocRangeOf(state.ctx, anchor);    // 紧贴在上方的文档,可能没有
  // 文档区间要单独留着:密度统计里它已经由 fn.doc 计过,整行注释集合里不能再算一次
  if (docRange) state.docRanges.push(docRange);
  state.facts.push(buildFunction(state.ctx, node, name, isWiring, docRange));
}

/**
 * 命名者给的文档锚点。
 *
 * `const f = () => {}` 的注释写在整个声明上方,而变量声明节点的前导 trivia 从
 * `const` 之后才开始 —— 直接拿它去找,注释永远找不到,于是每一个带文档的箭头函数
 * 都会被报成 `no-docstring`。往上走一层拿到那条语句,注释才在它的前导 trivia 里。
 *
 * @param {object} node 命名者节点(变量声明、属性、赋值)。
 * @returns {object} 用来找文档的节点。
 */
function docAnchorOf(node) {
  // 变量声明的上一级是声明列表,再上一级才是那条语句
  if (ts.isVariableDeclaration(node)) return node.parent && node.parent.parent ? node.parent.parent : node;
  // 属性与赋值节点的前导 trivia 已经覆盖了它上方的注释,直接用
  return node;
}

/**
 * 认下父节点给出的命名:`const f = () => {}` 的名字长在父节点上。
 *
 * 认过就记进 `claimed`,这样同一个函数节点走到自己那一轮时不会再按「匿名」记一条。
 *
 * @param {object} state 采集状态。
 * @param {object} node 可能是「命名者」的父节点。
 */
function claimNamed(state, node) {
  const inner = innerFunctionOf(node);    // 父节点里那个被命名的函数
  // 父节点不带函数,或它已经被别的父节点认过,都不再记
  if (
    // 父节点没有内嵌函数
    !inner ||
    // 或者它已经被认过
    state.claimed.has(inner)
  ) return;
  state.claimed.add(inner);
  addFact(state, docAnchorOf(node), inner, nameFromParent(state.ctx, node), isWiring(node));
}

/**
 * 深度优先遍历整棵语法树。
 *
 * 顺序是「先看自己,再问父节点给的命名」:反过来的话,`const f = () => {}`
 * 会先按匿名记一条,再被父节点记第二条。
 *
 * @param {object} state 采集状态。
 * @param {object} node 当前节点。
 */
function visitTree(state, node) {
  // 自身就是个函数/类
  if (isScopeNode(node)) {
    // 还没被父节点认过,就按自身声明的名字记一条
    if (!state.claimed.has(node)) {
      state.claimed.add(node);
      addFact(state, node, node, declaredName(node), isWiring(node));
    }
  }
  claimNamed(state, node);
  ts.forEachChild(node, (next) => visitTree(state, next));
}
