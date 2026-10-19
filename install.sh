#!/bin/sh
# wechatpush-rtbwmon installer — 在【路由器上】执行
#
# 用法:
#   sh install.sh /tmp/wechatpush.new    安装（/tmp/wechatpush.new 是 dist/wechatpush）
#   sh install.sh --restore              回滚到最近一次备份
#
# 授权: GPL-2.0
set -e

DST=/usr/share/wechatpush/wechatpush
RTB=/usr/libexec/rtbwmon.sh

if [ "$1" = "--restore" ]; then
	BAK=$(ls -1t "${DST}".bak.* 2>/dev/null | head -n1 || true)
	if [ -z "$BAK" ]; then
		echo "错误: 没有找到备份 ${DST}.bak.*"
		exit 1
	fi
	cp -f "$BAK" "$DST"
	chmod 755 "$DST"
	echo "已回滚: $BAK -> $DST"
	/etc/init.d/wechatpush restart
	echo "完成。"
	exit 0
fi

SRC="$1"
if [ -z "$SRC" ]; then
	echo "用法: sh $0 <已打补丁的 wechatpush 文件>"
	echo "      sh $0 --restore"
	exit 1
fi

[ -f "$SRC" ] || { echo "错误: 文件不存在: $SRC"; exit 1; }
[ -f "$DST" ] || { echo "错误: 未找到 $DST，请先安装 luci-app-wechatpush"; exit 1; }

command -v bash >/dev/null 2>&1 || { echo "错误: 缺少 bash，请先 opkg install bash"; exit 1; }

if [ -x "$RTB" ]; then
	echo "[1/5] 数据源: $RTB 存在"
else
	echo "[1/5] 警告: 未找到 $RTB（luci-app-rtbwmon 未安装？）统计将不可用"
fi

# 插件解释器是 bash（含 herestring），必须用 bash -n
if bash -n "$SRC"; then
	echo "[2/5] 语法校验通过"
else
	echo "错误: 语法校验失败，已中止（原文件未改动）"
	exit 1
fi

if grep -q 'rtbwmon' "$SRC"; then
	echo "[3/5] 确认是带 rtbwmon 适配的版本"
else
	echo "[3/5] 警告: 目标文件里没有 rtbwmon 字样，请确认这是打过补丁的文件"
fi

BAK="${DST}.bak.$(date +%Y%m%d%H%M%S)"
cp -a "$DST" "$BAK"
echo "[4/5] 已备份原文件: $BAK"

cp -f "$SRC" "$DST"
chmod 755 "$DST"
/etc/init.d/wechatpush restart
echo "[5/5] 已重启 wechatpush"

sleep 5
echo
echo "--- /tmp/wechatpush/usage.db ---"
if [ -f /tmp/wechatpush/usage.db ]; then
	head -5 /tmp/wechatpush/usage.db
	echo "共 $(grep -c '' /tmp/wechatpush/usage.db) 行"
else
	echo "尚未生成，最多等一个轮询周期（默认 60s）再看"
fi
echo
echo "完成。回滚请执行: sh $0 --restore"
