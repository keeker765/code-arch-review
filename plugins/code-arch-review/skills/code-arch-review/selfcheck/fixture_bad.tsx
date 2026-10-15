/**
 * 自检夹具(**阳性对照**,TSX 档):这份文件故意写坏,闸必须报出违规。
 *
 * 它验的是 `.tsx` 走的是 **TSX** 脚本种类。判成普通 TS 的话,下面那个 JSX 标签会被
 * 当成类型断言,这个文件整片解析失败 —— 而后端遇到解析失败不会报错停下,它是
 * **降级成启发式**的:这一份从此少查一大截(结果仍带 `(启发式)` 标记、stderr 也有一行
 * 提示,但那两条只在有人盯着看时才有用)。所以这一档最需要阳性样本:
 * 判错了必须在这里红,而不是安静地少报几条。
 *
 * 坏味道刻意选成**两档都报得出来**的:`no-docstring` 与逐条注释类规则在启发式档
 * 同样成立(见 `references/languages.md` 的 JS 一节),这样 `selfcheck` 在没装
 * `typescript` 的机器上跑也有对照。覆盖的规则:
 *
 * * `no-docstring`(`render` 与接口里的字段都没有文档)
 * * `many-kwargs`(`render` 要六个参数)
 * * `uncommented-assign`(`shown` 是 `filter` 算出来的)
 * * `uncommented-loop`(`for` 上方没有独立注释行)
 * * `uncommented-condition`(两个判据挤在同一行,上方也没有注释)
 * * `uncommented-field`(`Item.done` 没写口径;这条只有精确档报得出)
 */

/** 一件待办。 */
interface Item {
  /** 待办正文,直接显示在列表里。 */
  text: string;
  done: boolean;
}

export function render(items: Item[], limit: number, tag: string, extra: string, more: string, last: string) {
  const shown = items.filter((item) => !item.done);
  for (const item of items) {
    console.log(item.text);
  }
  if (shown.length === 0 && limit > 0) {
    console.log('empty');
  }
  return <ul>{shown.map((item) => <li key={item.text}>{item.text}</li>)}</ul>;
}
