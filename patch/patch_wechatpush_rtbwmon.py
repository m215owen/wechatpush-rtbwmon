#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wechatpush-rtbwmon patcher

把 tty228/luci-app-wechatpush 的 /usr/share/wechatpush/wechatpush 脚本
打补丁，使「客户端流量统计」改用 rtbwmon（nft 原生计数）而不是 wrtbwmon（iptables）。

用法:
    python3 patch_wechatpush_rtbwmon.py -s <原始 wechatpush> -o <输出文件>
    python3 patch_wechatpush_rtbwmon.py -s wechatpush.orig -o dist/wechatpush

说明:
    - 只在匹配到原文时替换，匹配失败会直接报错退出，不会产生半成品文件。
    - 可重复执行：已打过补丁的输入会被识别并拒绝。
    - 文件按原始换行符写回（不改变 CRLF/LF）。
"""

import argparse
import io
import sys

NOTICE = (
    "#\n"
    "# [MODIFIED] wechatpush-rtbwmon\n"
    "# 本文件修改自 tty228/luci-app-wechatpush v3.6.12 的 /usr/share/wechatpush/wechatpush\n"
    "# 修改内容：客户端流量统计的数据源由 wrtbwmon(iptables) 改为 rtbwmon(nft 原生计数)\n"
    "# 修改日期：2026-10-19\n"
    "# 修改者：m215owen  https://github.com/m215owen/wechatpush-rtbwmon\n"
    "# 许可：GPL-2.0（与上游项目一致）\n"
    "#\n"
)

# ---- 1) 依赖自检：rtbwmon 或 wrtbwmon 任一存在都不再告警 ----
OLD_CHECK = (
    '\t[ ! -f "/usr/sbin/wrtbwmon" ] && log_change '
    '"[WARN] $(translate "wrtbwmon not installed, traffic statistics unavailable")"'
)
NEW_CHECK = (
    '\t[ ! -x "/usr/libexec/rtbwmon.sh" ] && [ ! -f "/usr/sbin/wrtbwmon" ] '
    '&& log_change "[WARN] $(translate "wrtbwmon not installed, traffic statistics unavailable")"'
)

# ---- 2) usage() 首行守卫 + update 分支改为 rtbwmon ----
OLD_HEAD = '''usage() {
\t[ ! -f "/usr/sbin/wrtbwmon" ] || [ -z "$1" ] && return
\t# 更新
\tif [ $1 == "update" ]; then
\t\tversion_le() { test "$(echo "$@" | tr " " "\\n" | sort -n | head -n 1)" == "$1"; }
\t\tversion_ge() { test "$(echo "$@" | tr " " "\\n" | sort -r | head -n 1)" == "$1"; }
\t\t[ -n "$wr_version" ] && (version_ge "${wr_version}" "1.2.0") && wrtbwmon -f ${dir}/usage.db 2>/dev/null && return
\t\t[ -n "$wr_version" ] && (version_le "${wr_version}" "1.0.0") || [ -z "$wr_version" ] && wrtbwmon update ${dir}/usage.db 2>/dev/null && return'''

NEW_HEAD = '''usage() {
\t[ -z "$1" ] && return
\t# 更新
\tif [ $1 == "update" ]; then
\t\t# 优先使用 rtbwmon（nft 原生计数，适配 fw4/nftables 环境）
\t\tif [ -x "/usr/libexec/rtbwmon.sh" ]; then
\t\t\tlocal rtb_csv=$(/usr/libexec/rtbwmon.sh update 2>/dev/null)
\t\t\tif [ -n "$rtb_csv" ]; then
\t\t\t\tlocal rtb_now=$(date +%s)
\t\t\t\tlocal rtb_lan=$(uci -q get network.lan.device 2>/dev/null)
\t\t\t\t[ -z "$rtb_lan" ] && rtb_lan="br-lan"
\t\t\t\tlocal rtb_rows=$(echo "$rtb_csv" | awk -F, -v lan="$rtb_lan" 'NF >= 7 && $3 == lan')
\t\t\t\t[ -z "$rtb_rows" ] && rtb_rows="$rtb_csv"
\t\t\t\t{
\t\t\t\t\techo "mac,ip,iface,in,out,total,first,last"
\t\t\t\t\techo "$rtb_rows" | awk -F, -v ts="$rtb_now" '
\t\t\t\t\t\tNF >= 7 && $2 != "" && ($5 + $7) > 0 {
\t\t\t\t\t\t\tm = $2; t = ($5 + 0) + ($7 + 0)
\t\t\t\t\t\t\tif (t > best[m]) {
\t\t\t\t\t\t\t\tbest[m] = t
\t\t\t\t\t\t\t\tline[m] = sprintf("%s,%s,%s,%s,%s,%s,%s,%s", m, $1, $3, $5 + 0, $7 + 0, t, ts, ts)
\t\t\t\t\t\t\t}
\t\t\t\t\t\t}
\t\t\t\t\t\tEND { for (m in line) print line[m] }'
\t\t\t\t} > "${dir}/usage.db.tmp" 2>/dev/null && mv -f "${dir}/usage.db.tmp" "${dir}/usage.db"
\t\t\t\treturn
\t\t\tfi
\t\tfi
\t\t# 兼容原 wrtbwmon（仅当其仍存在时）
\t\t[ ! -f "/usr/sbin/wrtbwmon" ] && return
\t\tversion_le() { test "$(echo "$@" | tr " " "\\n" | sort -n | head -n 1)" == "$1"; }
\t\tversion_ge() { test "$(echo "$@" | tr " " "\\n" | sort -r | head -n 1)" == "$1"; }
\t\t[ -n "$wr_version" ] && (version_ge "${wr_version}" "1.2.0") && wrtbwmon -f ${dir}/usage.db 2>/dev/null && return
\t\t[ -n "$wr_version" ] && (version_le "${wr_version}" "1.0.0") || [ -z "$wr_version" ] && wrtbwmon update ${dir}/usage.db 2>/dev/null && return'''

SHEBANG = "#!/bin/bash"


def main():
    ap = argparse.ArgumentParser(description="为 wechatpush 打 rtbwmon 适配补丁")
    ap.add_argument("-s", "--src", required=True, help="原始 wechatpush 脚本路径")
    ap.add_argument("-o", "--out", required=True, help="输出（已打补丁）的文件路径")
    args = ap.parse_args()

    with io.open(args.src, "r", encoding="utf-8", newline="") as f:
        text = f.read()

    if "wechatpush-rtbwmon" in text and "/usr/libexec/rtbwmon.sh" in text:
        print("ERR: 输入文件看起来已经打过补丁了，请改用原始文件作为输入。")
        return 1

    if not text.startswith(SHEBANG):
        print("ERR: 文件头不是 '#!/bin/bash'，可能不是 wechatpush 主脚本。")
        return 1

    changes = []

    # 0) GPL-2.0 要求的改动声明
    nl = "\r\n" if "\r\n" in text[:200] else "\n"
    rest = text[len(SHEBANG) + len(nl):]
    text = SHEBANG + nl + NOTICE.replace("\n", nl) + rest
    changes.append("插入 GPL-2.0 改动声明")

    # 1) 依赖自检
    if OLD_CHECK not in text:
        print("ERR: 依赖自检行未匹配，请确认上游版本（本补丁针对 v3.6.12）。")
        return 1
    text = text.replace(OLD_CHECK, NEW_CHECK, 1)
    changes.append("依赖自检 -> rtbwmon / wrtbwmon 双识别")

    # 2) usage() update 分支
    if OLD_HEAD not in text:
        print("ERR: usage() 头部未匹配，请确认上游版本（本补丁针对 v3.6.12）。")
        return 1
    text = text.replace(OLD_HEAD, NEW_HEAD, 1)
    changes.append("usage() update 分支 -> rtbwmon（LAN 接口过滤 + MAC 归并 + 零流量剔除）")

    with io.open(args.out, "w", encoding="utf-8", newline="") as f:
        f.write(text)

    print("OK 已生成: %s" % args.out)
    for c in changes:
        print("  - %s" % c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
