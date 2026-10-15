/**
 * 自检夹具(**阴性对照**):这份文件故意写得完全合规,闸必须报 0 违规。
 *
 * 它验的是 JS/TS 后端的「不误报」方向:命名箭头函数、类字段与方法、`for-of` 循环、
 * 有处理体的 `try`/`catch`、带完整 JSDoc 小节的函数,都不该被闸挑出毛病。
 * 它与 `fixture_bad.js`(阳性对照)成对使用 —— 只有阴性对照时,一个恒绿的假后端
 * 能骗过全部自检;只有阳性对照时,判据写宽了也没人发现。
 */

/** 汇率的放大倍数:放大成整数再算,避免逐行浮点累加误差。 */
const RATE_SCALE = 100;

/**
 * 把每行金额按汇率折算,结果保留两位小数的定点表示。
 *
 * 夹具用它在精确档里制造一次「算出来的赋值」与一次循环 —— 前者要求赋值上方或行尾
 * 有注释,后者要求上方有独立整行注释。两者在这里都写到了,闸就该一声不吭。
 *
 * @param {number[]} amounts 各行金额,单位是原币。
 * @param {number} rate 汇率,原币兑人民币。
 * @returns {number[]} 折算后的金额,顺序与入参一致。
 */
function convert(amounts, rate) {
  const scaled = rate * RATE_SCALE;    // 汇率先放大成整数,后面每行都不必再乘
  const out = [];
  // 逐行折算:行数不多,不做向量化,读起来直白
  for (const amount of amounts) {
    // 四舍五入到分,报表上的金额不会出现第三位小数
    out.push(Math.round(amount * scaled) / RATE_SCALE);
  }
  // 返回与入参同序的折算结果
  return out;
}

/**
 * 一张流水账:每笔金额与备注成对记进台账。
 *
 * 夹具拿它验两件事:类本身按 `is_class` 报一条事实(不查参数表与嵌套层数),
 * 而类里的字段与方法各自按字段与函数的规矩查 —— 两套判据不能互相串。
 */
class Ledger {
  /**
   * 建一本台账。
   *
   * @param {string} title 台账名,报表标题用它。
   */
  constructor(title) {
    this.title = title;
  }

  /** 台账名,由构造函数写入;报表标题直接读它。 */
  title;

  /** 已记下的流水,每条是 `{amount, note}`;数组下标就是流水序号。 */
  rows = [];

  /**
   * 记一笔流水。
   *
   * 金额与备注成对存,读的时候不必再按下标猜哪个是哪个 —— 这是夹具里唯一一处
   * 同时有参数、有返回值的类方法,用来验 `@param` 与 `@returns` 两个小节。
   *
   * @param {number} amount 金额,单位元。
   * @param {string} note 备注,写清这笔钱花在哪。
   * @returns {{amount: number, note: string}} 记下的那一笔。
   */
  add(amount, note) {
    const entry = {amount, note};    // 成对存,读的时候不必按下标猜
    this.rows.push(entry);
    // 返回记下的那一笔,调用方可以立刻回显
    return entry;
  }
}

/**
 * 把一笔流水格式化成一行文本。
 *
 * 夹具用**命名的箭头函数**验「父节点给名字」这条路:名字长在变量声明上,
 * 而它同样是公开接口,同样要 JSDoc —— 这一条最容易在真解析里被漏掉。
 *
 * @param {{amount: number, note: string}} entry 一笔流水。
 * @returns {string} 制表符分隔的一行文本。
 */
const formatEntry = (entry) => {
  const amount = entry.amount.toFixed(2);    // 金额固定两位小数,报表要对齐
  // 制表符分隔,粘贴进表格就是两列
  return `${amount}\t${entry.note}`;
};

/**
 * 读一份 JSON 配置。
 *
 * 夹具验的是「有处理体的 catch 不算静默」:捕获之后必须真的做点什么,
 * 只有 `catch {}` 那种空块才是失败态与正常态同形。
 *
 * @param {string} raw 配置原文。
 * @returns {object|null} 解析结果;解析不了给 null。
 */
function loadConfig(raw) {
  try {
    return JSON.parse(raw);    // 解析成功就是配置本身
  } catch (error) {
    // 解析失败给 null,但先把原因说出来 —— 静默吞掉会让调用方以为配置是空的
    console.warn('配置解析失败', error);
    return null;
  }
}
