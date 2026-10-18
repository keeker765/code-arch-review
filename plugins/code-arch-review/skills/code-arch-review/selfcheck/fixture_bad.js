/**
 * 自检夹具(**阳性对照**):这份文件故意写坏,闸必须报出违规。
 *
 * 它验的是 JS/TS 后端的「报得出来」方向。只有阴性对照时,一个恒绿的假后端能骗过
 * 全部自检 —— 所以每一类坏味道在这里都留了一个最小可判的形态。
 *
 * 覆盖的规则(括号里是对应的样本):
 *
 * * `no-docstring`(`bareFunction`、类 `Rough` 与它的方法)
 * * `thin-docstring` / `docstring-sections`(`thinDoc` 只有一行摘要,且缺两个小节)
 * * `uncommented-condition`(`messy` 把两个判据挤在一行;`deepNest` 的五层 if 都没有注释)
 * * `uncommented-loop`(`messy` 的 `for` 上方空着;`throw` / `return` 不再单独要求注释)
 * * `uncommented-assign`(`messy` 的 `total` 是算式赋值)
 * * `uncommented-flat`(`flatRun` 里十二条赋值一行注释都没有)
 * * `uncommented-field`(`Rough` 的两个字段没写单位与口径)
 * * `silent-except`(`messy` 的 `catch` 是空的)
 * * `duplicate-toplevel`(`dup` 声明了两次,后一次静默胜出)
 * * `packed-layout`(`packedSecond` 与上一个定义之间一行空行都没有)
 * * `many-kwargs`(`tooManyParams` 要六个参数)
 * * `deep-nesting`(`deepNest` 套了五层 `if`)
 */

function bareFunction(value) {
  return value + 1;
}

/** 只有一行摘要,没有解释段。 */
function thinDoc(rows) {
  const kept = rows.filter((row) => row > 0);
  const scaled = kept.map((row) => row * 2);
  const total = scaled.length;
  const head = scaled[0] || 0;
  const tail = scaled[scaled.length - 1] || 0;
  return {total, head, tail};
}

function packedFirst() {
  return 1;
}
function packedSecond() {
  return 2;
}

function tooManyParams(alpha, beta, gamma, delta, epsilon, zeta) {
  return alpha + beta + gamma + delta + epsilon + zeta;
}

function deepNest(flag) {
  if (flag) {
    if (flag) {
      if (flag) {
        if (flag) {
          if (flag) {
            return 1;
          }
        }
      }
    }
  }
  return 0;
}

function messy(values, limit) {
  const total = values.reduce((sum, item) => sum + item, 0);
  for (const item of values) {
    console.log(item);
  }
  if (Array.isArray(values) && limit > total) {
    console.log('too big');
  }
  if (total < 0) {
    throw new Error('negative');
  }
  try {
    JSON.parse('{}');
  } catch (error) {
  }
  return total * 2;
}

class Rough {
  count = 0;
  label = '';

  bump() {
    this.count = this.count + 1;
  }
}

function dup() {
  return 'first';
}

function dup() {
  return 'second';
}

function flatRun() {
  const a = 1;
  const b = 2;
  const c = 3;
  const d = 4;
  const e = 5;
  const f = 6;
  const h = 7;
  const i = 8;
  const j = 9;
  const k = 10;
  const g = a + b + c + d + e + f;
  return g;
}
