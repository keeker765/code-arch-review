/**
 * AST 谓词与跨度:回答「这个节点是什么」和「它占几行」。
 *
 * 这一层不做任何判断,只把 TypeScript 的节点种类归一成后端用得到的几个概念:
 * 函数、类、作用域、名字、体量。函数事实的拼装(`js_functions`)与行级构造的采集
 * (`js_shapes`)都站在这里 —— 两边必须对「什么算函数」有同一个答案,否则
 * 覆盖率的分母会与分子分叉,而分叉时两个数都不报错。
 */
import { ts } from './js_ts.mjs';
import { lineOf } from './js_source.mjs';

/**
 * 带实现体的函数节点。接口/重载里没有身体的签名不算 —— 它们没有可判定的结构。
 *
 * 七种函数形态收在一处,是为了让「什么算函数」只有一份答案:少认一种,那一类函数
 * 里的分支、循环、赋值就整片不进覆盖率的分母,而分母变小是静默的。
 *
 * @param {object} node 任意 AST 节点。
 * @returns {boolean} 带体的函数给 true。
 */
export function isFunctionNode(node) {
  // 函数声明:TS 的重载签名没有 body,那种不算
  if (ts.isFunctionDeclaration(node)) return Boolean(node.body);
  // 类方法:抽象方法同样可以没有 body
  if (ts.isMethodDeclaration(node)) return Boolean(node.body);
  // 函数表达式:`function () {}` 本身就是函数
  if (ts.isFunctionExpression(node)) return true;
  // 箭头函数:同上,表达式体也算
  if (ts.isArrowFunction(node)) return true;
  // 构造函数:类里唯一一个名字不是普通标识符的方法
  if (ts.isConstructorDeclaration(node)) return true;
  // getter:对外可读,是一条接口
  if (ts.isGetAccessorDeclaration(node)) return true;
  // setter:同上
  if (ts.isSetAccessorDeclaration(node)) return true;
  // 其余节点(含对象字面量的简写方法,它由 isMethodDeclaration 覆盖)都不是
  return false;
}

/**
 * 类声明与类表达式。
 *
 * @param {object} node 任意 AST 节点。
 * @returns {boolean} 是类给 true。
 */
export function isClassNode(node) {
  return ts.isClassDeclaration(node) || ts.isClassExpression(node);    // 两种写法的判定在 TS 里是两个函数
}

/**
 * 自成一个作用域的节点:函数或类。
 *
 * 独立函数的意义在于后续每个「不下钻」的判定都写这一句:嵌套函数的条件是另一个
 * 契约,它的分支不该算进外层的嵌套深度,它的 return 也不该让外层要求 `@returns`。
 *
 * @param {object} node 任意 AST 节点。
 * @returns {boolean} 是函数或类给 true。
 */
export function isScopeNode(node) {
  return isFunctionNode(node) || isClassNode(node);    // 两种作用域边界的并集
}

/**
 * 属性名/变量名归一成可读文本:字符串名去掉引号,计算名给个占位。
 *
 * 归一的意义在报告:读者看到的是 `foo` 而不是 `"foo"`,看到 `<computed>` 就知道
 * 这里是个算出来的键、不是作者偷懒没写名字。
 *
 * @param {object} name 名字节点。
 * @returns {string} 可读名字;拿不到给空串。
 */
export function nameText(name) {
  // 匿名(回调、默认导出)没有名字,给空串让报告退化成行号
  if (!name) return '';
  // 标识符、字符串属性名、数字属性名都能直接取文本
  if (
    // 标识符:`foo`
    ts.isIdentifier(name) ||
    // 引号属性名:`{"foo bar": 1}`
    ts.isStringLiteral(name) ||
    // 数字属性名:`o[0]` 里的 0
    ts.isNumericLiteral(name)
  ) return name.text;
  // 计算属性名 `[expr]` 的文本不可读,给固定占位
  if (ts.isComputedPropertyName(name)) return '<computed>';
  // 其余形态(解构等)拿不到单一名,给空串
  return '';
}

/**
 * 这个成员是不是 private(TS 的 `private` 修饰符)—— 私有方法不是对外接口。
 *
 * `modifiers` 属性在 TS 4.x 之后要靠 `getModifiers` 取,两种取法都要认。
 *
 * @param {object} node 类成员节点。
 * @returns {boolean} 带 private 修饰给 true。
 */
export function hasPrivateModifier(node) {
  const modifiers = node.modifiers || (ts.canHaveModifiers && ts.getModifiers ? ts.getModifiers(node) : null);    // 新旧两代 API 都试一遍
  return Boolean(modifiers && modifiers.some((item) => item.kind === ts.SyntaxKind.PrivateKeyword));    // 修饰符表里找 private
}

/**
 * 定义自身的名字;匿名(回调、默认导出)给空串,报告里退化成行号。
 *
 * 与 `nameText` 的区别是它认得「没有名字」的两种函数:构造函数与读写器在 AST 里
 * 没有普通名字节点,直接取会得到空串,报告里就只剩一个行号。
 *
 * @param {object} node 函数或类节点。
 * @returns {string} 名字。
 */
export function declaredName(node) {
  // 构造函数没有名字节点,补一个约定名
  if (ts.isConstructorDeclaration(node)) return 'constructor';
  // getter 用 `get x` 标明读的是属性而不是调用
  if (ts.isGetAccessorDeclaration(node)) return `get ${nameText(node.name)}`;
  // setter 同理,读法不同而已
  if (ts.isSetAccessorDeclaration(node)) return `set ${nameText(node.name)}`;
  return nameText(node.name);    // 普通声明直接取名字节点的文本
}

/**
 * 参数名列表。TS 的 `this` 形参与 Python 的 self 同类:调用方从不传它,不计入。
 *
 * 解构参数(`{a, b}`、`[x]`)拿不到单一名,退化成源码文本 —— 报「参数有 1 个」总比
 * 报 0 个好:0 会让 `many-kwargs` 与文档小节一起判错。
 *
 * @param {object} node 函数节点。
 * @returns {string[]} 参数名列表。
 */
export function paramNames(node) {
  const names = [];
  // 逐个参数取值;函数节点没有 parameters 字段时按空表处理
  for (const parameter of node.parameters || []) {
    const name = parameter.name;
    // 没有名字节点的参数(极少数语法)跳过
    if (!name) continue;
    // 裸标识符是最常见的一种
    if (ts.isIdentifier(name)) {
      // this 形参是类型标注,不是真实入参,与 Python 的 self 同理
      if (name.text === 'this') continue;
      names.push(name.text);
      continue;
    }
    // 解构、默认值等形态退化成源码文本,压掉换行让报告里只占一行
    names.push(name.getText().replace(/\s+/g, ' '));
  }
  return names;
}

/**
 * 定义起始行:优先取名字那一行,匿名节点才退回节点起点。
 *
 * 装饰器与 `export` 都在名字之上,按它们报会把行号指到别处 —— 报告里那一行
 * 应该是读者要跳过去的那一行。
 *
 * @param {object} ctx 解析上下文。
 * @param {object} node 定义节点。
 * @returns {number} 1 基行号。
 */
export function startLineOf(ctx, node) {
  // 有名字就报名字那一行
  if (node.name) return lineOf(ctx, node.name.getStart());
  return lineOf(ctx, node.getStart());    // 匿名节点(回调、默认导出)才退回节点起点
}

/**
 * 类的成员列表。
 *
 * TS 4.0 起类体是独立的 ClassBody 节点(`node.body.members`),3.x 里成员直接挂在类节点上。
 * 两种形状都要认 —— 探测到的 typescript 可能是任何一个版本。
 *
 * @param {object} node 类节点。
 * @returns {object[]} 成员列表。
 */
export function classMembersOf(node) {
  const body = node.body;
  // 4.0 及以后:类体是独立节点,里面有 members
  if (
    // 类体节点存在
    body &&
    // 且它是带成员的 ClassBody
    body.members
  ) return body.members;
  return node.members || [];    // 3.x:成员直接挂在类节点上
}

/**
 * 函数体行数:首尾语句之间的跨度(与 Python 后端的 `body[-1].end - body[0].start + 1` 同口径)。
 *
 * 空体给 0 —— 没有语句就没有可判定的体量,`long-function` 等规则会自然跳过它。
 * 类也一样按成员列表的跨度算,否则「上帝类」永远量不出来。
 *
 * @param {object} ctx 解析上下文。
 * @param {object} node 函数或类节点。
 * @returns {number} 体行数;空体给 0。
 */
export function bodyLinesOf(ctx, node) {
  // 类的体量算成员列表的跨度:类没有语句块
  if (isClassNode(node)) return spanOf(ctx, classMembersOf(node));
  const body = node.body;
  // 没有体的签名(接口、抽象方法)就没有可判定的体量
  if (!body) return 0;
  // 块体按首尾语句的跨度算
  if (body.statements) return spanOf(ctx, body.statements);
  // 表达式体(单表达式箭头)只有它自己那一行
  return lineOf(ctx, body.getEnd()) - lineOf(ctx, body.getStart()) + 1;
}

/**
 * 一组语句/成员的首尾跨度;空列表给 0。
 *
 * 用的是「最后一条的结束行 − 第一条的开始行 + 1」,与 Python 后端同口径:
 * 中间的空行与注释都算在内,因为读者翻的就是这一段。
 *
 * @param {object} ctx 解析上下文。
 * @param {object[]} items 语句或成员列表。
 * @returns {number} 跨度行数。
 */
export function spanOf(ctx, items) {
  // 空列表没有跨度
  if (!items.length) return 0;
  return lineOf(ctx, items[items.length - 1].getEnd()) - lineOf(ctx, items[0].getStart()) + 1;    // 首尾两条之间的行数
}

/**
 * 子树里有没有满足条件的语句,**不下钻嵌套函数** —— 那是另一个契约。
 *
 * `sectionFacts` 靠它回答「这个函数体里有没有 return 表达式、有没有 throw」,
 * 而那正是 `@returns` / `@throws` 两个小节的判据;不下钻保证了内层闭包的 return
 * 不会让外层凭空多要求一个小节。
 *
 * @param {object} root 子树根节点。
 * @param {Function} predicate 节点种类判定。
 * @param {Function} detail 进一步的条件判定。
 * @returns {boolean} 找到给 true。
 */
export function subtreeHas(root, predicate, detail) {
  let found = false;

  /**
   * 深度优先找第一个满足条件的语句;遇到嵌套作用域就停。
   *
   * 用函数声明而不是箭头常量:`jsDocRangeOf` 取的是节点自身的前导注释,
   * 箭头函数在 `const f = ...` 里前面隔着 `=` 与空格,注释取不到。
   *
   * @param {object} node 当前节点。
   */
  function visit(node) {
    // 已经找到就不必再走
    if (found) return;
    // 嵌套的函数/类自成一个契约,它的 return 不该算到外层头上
    if (
      // 不是本次扫描的根
      node !== root &&
      // 而是一个嵌套的作用域
      isScopeNode(node)
    ) return;
    // 命中判据就记下并停止
    if (
      // 节点种类对
      predicate(node) &&
      // 附加条件也对
      detail(node)
    ) {
      found = true;
      return;
    }
    ts.forEachChild(node, visit);
  }

  // 空子树(比如没有 body 的签名)直接给 false
  if (root) visit(root);
  return found;
}

/**
 * 这个节点是不是**嵌套**的一层。
 *
 * `else if` 是平铺的连写,不是嵌套:把它算一层的话,一长串 `else if` 会假装成深嵌套,
 * 而那是 JS 里最常见的分支写法之一。
 *
 * @param {object} node 任意 AST 节点。
 * @param {boolean} isElseBranch 它是不是上层 `if` 的 else 分支。
 * @returns {boolean} 算一层给 true。
 */
export function addsDepth(node, isElseBranch) {
  // else 分支上的 if 就是 else if,与链首平级
  if (
    // 挂在 else 分支上
    isElseBranch &&
    // 而它又是一个 if
    ts.isIfStatement(node)
  ) return false;
  // 其余八种控制流语句每个算一层
  return ts.isIfStatement(node)
    || ts.isForStatement(node)
    || ts.isForInStatement(node)
    || ts.isForOfStatement(node)
    || ts.isWhileStatement(node)
    || ts.isDoStatement(node)
    || ts.isSwitchStatement(node)
    || ts.isTryStatement(node)
    || ts.isWithStatement(node);
}
