/**
 * 行级构造:条件、循环、抛异常、字段、赋值、返回、静默 catch、顶层绑定。
 *
 * 这些是覆盖率的分母 —— 报告里的「注释覆盖率」问的就是「这些该解释的地方解释了没有」。
 * 所以每一类都只有一个采集口径,且**与规则引擎的判据一一对应**:这里多收一条,
 * 覆盖率就白掉一格;少收一条,那一类问题就整片看不见。
 *
 * 采集一律用 `walkAll`(不分作用域),只有条件例外 —— 模块顶层的 `if` 没有业务判据,
 * 收进来只会让 `uncommented-condition` 去要求给构建脚本的分支写注释。
 */
import { ts } from './js_ts.mjs';
import { lineOf } from './js_source.mjs';
import { isFunctionNode, startLineOf, nameText, subtreeHas } from './js_nodes.mjs';

/* ------------------------------------------------------------------ 条件与循环 */

/**
 * 把 `&&` / `||` 摊平成一个个独立判据。
 *
 * `a && b` 是两个判据,即使写在同一行也记两次 —— 这份摊平数据只作诊断,
 * 2026-10-18 起注释规则只看条件起始行。括号要脱掉,否则摊平结果会多算一层。
 *
 * @param {object} node 条件表达式。
 * @param {object[]} out 结果累积数组。
 * @returns {object[]} 摊平后的判据列表。
 */
export function flattenOperands(node, out) {
  // 括号只是写法,先脱掉再判
  if (ts.isParenthesizedExpression(node)) return flattenOperands(node.expression, out);
  const isBooleanOperator = ts.isBinaryExpression(node)    // 只有逻辑与、逻辑或是判据的连接词
    && (
      node.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken
      || node.operatorToken.kind === ts.SyntaxKind.BarBarToken
    );    // 只有逻辑与、逻辑或是「判据的连接词」
  // 逻辑运算符就把两边各自摊平
  if (isBooleanOperator) {
    flattenOperands(node.left, out);
    flattenOperands(node.right, out);
    return out;
  }
  out.push(node);
  return out;
}

/**
 * 全部 `if` / `else if` 事实。
 *
 * 只收**函数体内**的:模块顶层的 `if` 没有业务判据(与 Python 后端口径一致)。
 *
 * @param {object} ctx 解析上下文。
 * @returns {object[]} 每条含 line 与被摊平的 operand_lines。
 */
export function collectConditions(ctx) {
  const out = [];

  /**
   * 深度优先,记住当前是不是已经进了函数体。
   *
   * 状态往下传而不是往上找:节点没有 parent 指针上的「是不是在函数里」,
   * 每次回头爬一遍祖先会把遍历变成平方级。
   *
   * @param {object} node 当前节点。
   * @param {boolean} inFunction 外层是不是已经在函数体内。
   */
  function visit(node, inFunction) {
    const inside = inFunction || isFunctionNode(node);    // 进了函数体就一直是里面
    // 只收函数体内的 if
    if (
      // 已经在函数体内
      inside &&
      // 且这是一个 if
      ts.isIfStatement(node)
    ) {
      out.push({
        line: lineOf(ctx, node.getStart()),
        operand_lines: flattenOperands(node.expression, []).map((item) => lineOf(ctx, item.getStart())),
      });
    }
    ts.forEachChild(node, (child) => visit(child, inside));
  }

  visit(ctx.sf, false);
  return out;
}

/**
 * 循环事实。行尾注释不算 —— 循环上方要写「遍历什么、为什么必须循环」,一行放不下。
 *
 * 五种循环分开标 label 是为了让报告能说清是哪一种:`for-of` 与 `for` 要解释的东西
 * 不一样,只写「循环」等于让读者回去翻源码。
 *
 * @param {object} ctx 解析上下文。
 * @returns {object[]} 每条含 line 与 label。
 */
export function collectLoops(ctx) {
  const out = [];
  const labels = [
    [ts.isForStatement, 'for'],
    [ts.isForInStatement, 'for-in'],
    [ts.isForOfStatement, 'for-of'],
    [ts.isWhileStatement, 'while'],
    [ts.isDoStatement, 'do'],
  ];
  walkAll(ctx, (node) => {
    // 逐个种类比,命中就记一条并停止 —— 五种互斥,不必比完
    for (const [matches, label] of labels) {
      // 命中这一种
      if (matches(node)) {
        out.push({line: lineOf(ctx, node.getStart()), label});
        return;
      }
    }
  });
  return out;
}

/**
 * 抛异常事实。`throw` 是把失败态交给调用方,上方必须有独立注释行。
 *
 * 与 `raise` 的 Python 口径一致:注释要写「什么前提被破坏了、调用方该怎么改」,
 * 而不是复述一遍异常消息 —— 消息在代码里已经有了。
 *
 * @param {object} ctx 解析上下文。
 * @returns {object[]} 每条含 line 与 label。
 */
export function collectThrows(ctx) {
  const out = [];
  walkAll(ctx, (node) => {
    // throw 语句自身就是全部判据,不必再看子节点
    if (ts.isThrowStatement(node)) out.push({line: lineOf(ctx, node.getStart()), label: 'throw'});
  });
  return out;
}

/**
 * 遍历整棵树,不管作用域。
 *
 * 与 `visitTree` 那套「认父亲给的名字」的遍历不同:这里只关心节点出现了没有,
 * 嵌套与否不影响采集结果。
 *
 * @param {object} ctx 解析上下文。
 * @param {Function} onNode 每个节点调一次。
 */
export function walkAll(ctx, onNode) {
  /** 深度优先走整棵树。 */
  function visit(node) {
    onNode(node);
    ts.forEachChild(node, visit);
  }

  visit(ctx.sf);
}

/* ------------------------------------------------------------------ 字段与赋值 */

/**
 * 类字段与 TS 属性签名 —— 「这个数是什么、什么单位」的唯一落点。
 *
 * 箭头函数字段要跳过:它已经被 `collectFunctions` 当成方法记过一条,
 * 这里再报一次会让同一个成员在报告里出现两遍,一处改完另一处还在。
 *
 * 属性签名只收**声明出来的类型**的成员(接口体、类型别名里的对象类型)。
 * 参数上的内联类型(`props: {items: Todo[]}`)不算:那种形状的归属地是参数自己的
 * JSDoc,在参数行上方再插一行注释只会把函数签名挤成两倍长。
 *
 * @param {object} ctx 解析上下文。
 * @param {Set<object>} claimedFunctions 已经被记成函数的节点(箭头函数字段)。
 * @returns {object[]} 每条含 line 与 label。
 */
export function collectFields(ctx, claimedFunctions) {
  const out = [];
  walkAll(ctx, (node) => {
    // 类字段:箭头函数字段已经在函数清单里报过,不再重复报字段
    if (ts.isPropertyDeclaration(node)) {
      // 箭头函数字段当成方法看(它确实是个方法)
      if (claimedFunctions.has(node.initializer)) return;
      out.push({line: startLineOf(ctx, node), label: nameText(node.name)});
      return;
    }
    // TS 属性签名:接口里的字段,同样要写清单
    if (ts.isPropertySignature(node)) {
      // 参数或变量上的内联类型字面量不是「声明出来的字段」,跳过
      if (!isDeclaredTypeMember(node)) return;
      out.push({line: startLineOf(ctx, node), label: nameText(node.name)});
    }
  });
  return out;
}

/**
 * 右侧是运算/调用的赋值。纯字面量不算 —— `limit = 8` 没什么可解释的。
 *
 * 只认裸名字与被赋值的目标是变量:属性赋值(`this.x = f()`)不进清单,
 * 与 Python 后端跳过 `self.x = ...` 同口径。
 *
 * @param {object} ctx 解析上下文。
 * @returns {object[]} 每条含 line 与 label。
 */
export function collectAssigns(ctx) {
  const out = [];
  walkAll(ctx, (node) => {
    // 变量声明形态 `const x = ...`
    if (
      // 是变量声明
      ts.isVariableDeclaration(node) &&
      // 名字是裸标识符(解构声明没有单一名字)
      ts.isIdentifier(node.name) &&
      // 右侧是算出来的
      isComputed(node.initializer)
    ) {
      out.push({line: lineOf(ctx, node.getStart()), label: node.name.text});
      return;
    }
    // 普通赋值形态 `x = ...`
    if (
      // 是二元表达式
      ts.isBinaryExpression(node) &&
      // 运算符是赋值类
      isAssignmentOperator(node) &&
      // 左值是裸标识符
      ts.isIdentifier(node.left) &&
      // 右侧是算出来的
      isComputed(node.right)
    ) {
      out.push({line: lineOf(ctx, node.getStart()), label: node.left.text});
    }
  });
  return out;
}

/**
 * 赋值运算符(`=` 与 `+=` 这类复合赋值)。
 *
 * 用 TS 的 FirstAssignment..LastAssignment 区间判,而不是列出所有符号:
 * 语言新增一个复合赋值运算符时,这里不必跟着改。
 *
 * @param {object} node 二元表达式节点。
 * @returns {boolean} 是赋值运算符给 true。
 */
export function isAssignmentOperator(node) {
  const kind = node.operatorToken.kind;
  return kind >= ts.SyntaxKind.FirstAssignment && kind <= ts.SyntaxKind.LastAssignment;    // 区间两端的枚举值
}

/**
 * `return <算式>`:调用方拿到的口径要写在上面,不能靠反推表达式。
 *
 * 只收算式是因为算式才有口径问题:`return null` 与 `return this.items` 都不必解释,
 * 硬要求注释只会逼出一堆「返回空」这样的废话。
 *
 * @param {object} ctx 解析上下文。
 * @returns {object[]} 每条含 line 与 label。
 */
export function collectReturns(ctx) {
  const out = [];
  walkAll(ctx, (node) => {
    // 裸 return 没有口径可写,只收带表达式的
    if (
      // 是 return 语句
      ts.isReturnStatement(node) &&
      // 且带算式
      isComputed(node.expression)
    ) {
      out.push({line: lineOf(ctx, node.getStart()), label: 'return'});
    }
  });
  return out;
}

/**
 * 右侧算不算「算出来的」。`o.x` 这类取值不算(与 Python 后端跳过 Attribute 一致)。
 *
 * 判的是「读者能不能一眼看出值是什么」:字面量与裸名字可以,调用、运算、三元、
 * 模板串都要停下来想一想,那就要一行注释。
 *
 * @param {object} node 表达式节点,允许为 null。
 * @returns {boolean} 算出来的给 true。
 */
export function isComputed(node) {
  // 没有表达式(裸 return、裸赋值)不算
  if (!node) return false;
  // 二元运算:优先级与结合性都不必读者去推
  if (ts.isBinaryExpression(node)) return true;
  // 三元表达式:值取决于另一个条件
  if (ts.isConditionalExpression(node)) return true;
  // 函数调用:值取决于被调方的契约
  if (ts.isCallExpression(node)) return true;
  // new 表达式:与调用同理
  if (ts.isNewExpression(node)) return true;
  // 标签模板:`sql\`...\`` 这类拼出来的值
  if (ts.isTaggedTemplateExpression(node)) return true;
  // 模板串:插值算出来的
  if (ts.isTemplateExpression(node)) return true;
  // await:值取决于异步结果,不是眼前的字面量
  if (ts.isAwaitExpression(node)) return isComputed(node.expression);
  // 括号只影响写法,看里面
  if (ts.isParenthesizedExpression(node)) return isComputed(node.expression);
  // 其余(字面量、裸名字、属性取值、数组与对象字面量)读者一眼能看出值是什么
  return false;
}

/**
 * 空 catch:`catch {}` / `catch (e) {}` 体内一条语句都没有 —— 失败态与正常态同形。
 *
 * 这是最难查的一类 bug:调用方看到的是一个正常返回,而实际上那一步根本没做成。
 * 所以它不看注释、只看语句数 —— 有注释的静默吞异常同样是静默吞异常。
 *
 * @param {object} ctx 解析上下文。
 * @returns {number[]} 行号列表。
 */
export function collectSilentCatches(ctx) {
  const out = [];
  walkAll(ctx, (node) => {
    // 只有 catch 子句才判
    if (!ts.isCatchClause(node)) return;
    // 体存在且一条语句都没有
    if (
      // 有体
      node.block &&
      // 体里没有语句
      node.block.statements.length === 0
    ) out.push(lineOf(ctx, node.getStart()));
  });
  return out;
}

/* ------------------------------------------------------------------ 顶层绑定 */

/**
 * 模块顶层**直接**的 `function` / `class` / `var` 声明,判 `duplicate-toplevel` 用。
 *
 * `let` / `const` 重复声明是语法错误,引擎自己会报;只有 `var` 与 `function`
 * 是**静默后者胜出**,所以只收这两种(见 languages.md)。`export` 包一层要脱掉。
 *
 * @param {object} ctx 解析上下文。
 * @returns {object[]} 每条含 name、kind、line、references_self。
 */
export function collectBindings(ctx) {
  const out = [];
  // 只看模块顶层:函数体内的 var 不构成模块级重名
  for (const statement of ctx.sf.statements) {
    const inner = unwrapExport(statement);    // export 包一层就先脱掉
    // 顶层函数声明:名字与函数名同名,重复即静默覆盖
    if (
      // 是函数声明
      ts.isFunctionDeclaration(inner) &&
      // 有名字
      inner.name &&
      // 有函数体(重载签名不算绑定)
      inner.body
    ) {
      out.push({name: inner.name.text, kind: 'def', line: lineOf(ctx, inner.name.getStart()), references_self: false});
      continue;
    }
    // 顶层类声明:与函数同一条规则
    if (
      // 是类声明
      ts.isClassDeclaration(inner) &&
      // 有名字(匿名默认导出类不构成具名绑定)
      inner.name
    ) {
      out.push({name: inner.name.text, kind: 'def', line: lineOf(ctx, inner.name.getStart()), references_self: false});
      continue;
    }
    // 顶层 var:同一个名字声明两次同样静默后者胜出
    if (
      // 是变量语句
      ts.isVariableStatement(inner) &&
      // 且关键字是 var
      isVarKeyword(inner.declarationList)
    ) {
      // 一条声明里可以有多个变量
      for (const declaration of inner.declarationList.declarations) {
        // 解构声明没有单一名字,跳过
        if (!ts.isIdentifier(declaration.name)) continue;
        out.push({
          name: declaration.name.text,
          kind: 'assign',
          line: lineOf(ctx, declaration.name.getStart()),
          references_self: mentionsIdentifier(declaration.initializer, declaration.name.text),
        });
      }
    }
  }
  return out;
}

/**
 * 脱掉 `export` 外壳,拿到里面的声明。
 *
 * 只看 `declaration` 那一支:`export {a, b}` 与 `export * from` 没有声明体,
 * 它们不产生模块级绑定,拿不到就原样返回。
 *
 * @param {object} statement 顶层语句。
 * @returns {object} 里面的声明,或原语句。
 */
export function unwrapExport(statement) {
  // 不是 export 语句就原样返回
  if (!ts.isExportDeclaration(statement)) return statement;
  return statement.declaration || statement;    // export 没有声明体时原样返回
}

/**
 * 声明列表用的是不是 `var` 关键字(`let`/`const` 靠关键字判,不靠 flag 位)。
 *
 * @param {object} list 变量声明列表。
 * @returns {boolean} 是 var 给 true。
 */
export function isVarKeyword(list) {
  const first = list.getChildAt(0);    // 列表的第一个 token 就是关键字
  return Boolean(first && first.kind === ts.SyntaxKind.VarKeyword);    // 只有 var 才算
}

/**
 * 右侧表达式有没有引用这个名字 —— 那是扩展/规范化(`x = x.concat(...)`),不是覆盖。
 *
 * @param {object} node 右侧表达式。
 * @param {string} name 变量名。
 * @returns {boolean} 引用了给 true。
 */
export function mentionsIdentifier(node, name) {
  return subtreeHas(node, ts.isIdentifier, (item) => item.text === name);    // 子树里有同名标识符就算
}

/**
 * 属性签名是不是「声明出来的类型」的成员。
 *
 * 剥掉中间的 `{...}` 外壳,看最外层挂着的是接口声明还是类型别名 —— 只有那两种
 * 算模块里声明出来的形状。参数与变量上的内联类型字面量剥到最后会落在
 * `Parameter` / `VariableDeclaration` 上,那一类按「不是字段」处理。
 *
 * @param {object} node 属性签名节点。
 * @returns {boolean} 是声明出来的类型成员给 true。
 */
function isDeclaredTypeMember(node) {
  let current = node.parent;
  // 类型字面量只是外壳,一层层剥掉
  while (current && ts.isTypeLiteralNode(current)) current = current.parent;
  // 剥到接口或类型别名,才算声明出来的类型
  return Boolean(current && (ts.isInterfaceDeclaration(current) || ts.isTypeAliasDeclaration(current)));
}
