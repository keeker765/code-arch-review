#!/usr/bin/env bash
# 闸的 shell **合规样本**:每一类该解释的构造都说明到位,闸对它必须报 0 处违规。
# selfcheck/run.py 会自动 glob `fixture_clean.*` 并断言这一条。
#
# 它同时钉住几处最容易判反的地方,谁改后端改坏了就会在这里红:
#   * heredoc 体里的 `#` 与 `if` 不是注释、不是条件(整段都不是代码);
#   * 行尾 `&&` 与行尾反斜杠是续行 —— 一条条件不许算成两条,也不许算成挤行;
#   * 引号里的 `#` 不是注释,`echo a#b` 里的也不是(`#` 只在词的边界上才算);
#   * case 的分支臂自带结构,不被算成长平铺段。
#
# ⚠ 这是夹具,不执行:里面的 pkg_fetch / apply_glibc_shim 都是占位命令。
# ⚠ 改这个文件等于改闸的口径,动了要同步 selfcheck/run.py 的期望值(0 违规)。
set -euo pipefail

# 依赖清单由调用方给出;产物目录缺省 dist,不在这里造别的默认值
DEPS_FILE="${1:?用法: build.sh <deps-file> [out-dir]}"
OUT_DIR="${2:-dist}"

# 只在 Linux 与 Darwin 上下发预编译产物,其余平台必须走源码编译
if [ "$(uname -s)" = Linux ] ||
   # Darwin 与 Linux 共用同一套产物,只是下载源不同,所以并进同一个分支
   [ "$(uname -s)" = Darwin ]; then
    # 产物目录先清空:半旧的产物混进去会被当成这一次的产物
    rm -rf "$OUT_DIR"
fi

# 配置缺失就决定不了产物名,直接失败比产出名字错的文件好
if [ ! -f "$DEPS_FILE" ]; then
    # 调用方要修的是自己传的参数,不是重跑这个脚本
    exit 1
fi

# 装一个包并校验它的摘要:两步都成功才算装上
install_one() {
    # 摘要不匹配说明下载坏了,重试没有意义,交给调用方
    pkg_fetch "$1"
    pkg_verify "$1"
}

# 逐行读依赖清单:行与行之间有安装顺序,必须顺序处理,不能并行
while read -r name; do
    # 空行不是依赖,跳过
    if [ -z "$name" ]; then
        continue
    fi
    # 已经装过的包不再装一遍,省一次网络往返
    for pinned in $(list_installed); do
        # 命中就跳过这一条依赖
        if [ "$pinned" = "$name" ]; then
            continue 2
        fi
    done
    # 真正的安装在这里,失败由 set -e 交给调用方
    install_one "$name"
done < "$DEPS_FILE"

# 等锁文件消失:等的就是另一个进程放锁,除了轮询没有别的办法
until [ ! -f "$OUT_DIR/.lock" ]; do
    # 每轮只等一秒:锁的持有时间通常远小于一次下载
    sleep 1
done

# 平台补丁:三种平台的产物来源与签名都不同,用 case 比串一串 if 清楚
case "$(uname -s)" in
    Linux)
        # glibc 版本不够时补一层兼容垫片
        apply_glibc_shim
        ;;
    Darwin)
        # macOS 只需要重新签名,别的一律不动
        resign_bundle
        ;;
    *)
        # 其余平台没有补丁,明确报出来而不是静默跳过
        echo "no patch for this platform" >&2
        ;;
esac

# 产物清单写给人看;这里 `#` 是清单格式的一部分,不是注释
echo "artifacts#$(date +%s)" > "$OUT_DIR/manifest"

# 内嵌一段 Python 算校验和:里面的 `#` 与 `if` 都不是 shell 的东西
python3 - <<'PY'
# 这不是 shell 注释,后端不许把它算进注释行
if True:
    print('checksums')
PY

echo "打包完成:$OUT_DIR"
