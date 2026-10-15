/**
 * 自检夹具(**阴性对照**,TSX 档):这份文件故意写得完全合规,闸必须报 0 违规。
 *
 * 它验的是 `.tsx` 这一条扩展名走的是 TSX 脚本种类,而且 JSX **不会被误判**:
 * 泛型标注、类型断言与 JSX 标签在词法上长得很像,判错了整片文件会报语法错,
 * 而报语法错的文件会静默降级成启发式 —— 那种降级看起来像「扫过了」。
 *
 * 与 `fixture_bad.tsx` 无关:TSX 只做阴性对照,阳性方向由 `fixture_bad.js` 承担。
 */

/** 一件待办:文本与完成状态成对存,渲染时两样都要用。 */
export interface Todo {
  /** 待办正文,直接显示在列表里;不做转义,调用方自己保证它是纯文本。 */
  text: string;
  /** 是否已完成;已完成的那些不再计进剩余数。 */
  done: boolean;
}

/**
 * 数一数还有多少件没做完。
 *
 * 夹具拿它验接口里的**属性签名**会被收进字段清单 —— 字段只要求一行注释,
 * 不要求 JSDoc 小节,所以这里每个字段上方有一行注释就够。
 *
 * @param items 全部待办。
 * @returns 未完成的件数。
 */
export function remaining(items: Todo[]): number {
  const left = items.filter((item) => !item.done);    // 未完成的那些,顺序保持不变
  return left.length;
}

/**
 * 把待办渲染成一个列表。
 *
 * 夹具拿它验 JSX 能被解析:箭头函数写在标签里、泛型与断言混在类型标注里,
 * 这三样都过得了词法,才说明 `.tsx` 走的是 TSX 而不是 TS。
 *
 * @param props 组件属性,`items` 是全部待办。
 * @returns 一个列表元素。
 */
export function TodoList(props: {items: Todo[]}): JSX.Element {
  // 逐件渲染;key 用正文,夹具不关心重复文本的边界情况
  return <ul>{props.items.map((item) => <li key={item.text}>{item.text}</li>)}</ul>;
}
