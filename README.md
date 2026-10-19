# wechatpush-rtbwmon

让 [luci-app-wechatpush](https://github.com/tty228/luci-app-wechatpush) 的「客户端流量统计」在 **fw4 / nftables** 系统（OpenWrt 22.03+、24.10、iStoreOS）上正常工作——用系统自带的 **rtbwmon** 替代已经退役的 **wrtbwmon**。

- 无新增依赖：用 `luci-app-rtbwmon` 提供的 `/usr/libexec/rtbwmon.sh`（nft 原生计数）
- 不改动 wechatpush 的配置、推送、设备上下线、CPU/温度等任何其它功能
- 只改一个文件里的两处逻辑，`wrtbwmon` 分支保留为兜底

---

## 背景：为什么 wrtbwmon 用不了

wechatpush 的流量统计功能依赖 `wrtbwmon`（README 里也写明「流量统计功能依赖 wrtbwmon，需自行选装或编译」）。但 wrtbwmon 是 **iptables 时代**的工具，在 nftables 系统上有三重障碍：

**1. 包已经没了**

OpenWrt 24.10.8 官方软件源（x86_64 索引 4585 个包）里已无 `wrtbwmon`，只有同类替代 `nlbwmon`；iStoreOS 自有源也没有。所以新装系统上插件启动只会固定打印：

```
[WARN] 未安装 wrtbwmon，流量统计不可用
```

**2. 装了也跑不起来**

即使手动装第三方 [`wrtbwmon` 0.36](https://github.com/pyrovski/wrtbwmon)，在 fw4 系统上实测报错：

```
iptables v1.8.10 (nf_tables): table `mangle' is incompatible, use 'nft' tool to list them.
iptables v1.8.10 (nf_tables): CHAIN_ADD failed (File exists): chain OUTPUT
```

原因：`ip mangle` 表的基础链是 nft 原生创建的（OpenClash 等要打 ct mark），xtables 既读不了也挂不上跳转链。

**3. 还会污染解析**

iptables 会把一行警告打到 **stdout**：

```
# Table `mangle' contains incompatible base-chains, use 'nft' tool to list them.
```

这行被 wrtbwmon 的 `readDB.awk` 当成数据行解析，产出一个假 IP，后续 `iptables -s <垃圾值>` 报 `Bad argument`，整个统计链路崩掉。

结论：这套方案在现代 OpenWrt 上已经没有修复价值，换数据源才是正解。

---

## 方案：改用 rtbwmon（nft 原生）

大多数系统里已经有 `luci-app-rtbwmon`（1.1.0），它自带一个 nft 原生的计数实现 `/usr/libexec/rtbwmon.sh`，输出格式为：

```
ip,mac,iface,up_pkts,up_bytes,down_pkts,down_bytes,user
```

本补丁让 wechatpush 的 `usage()` 优先从这里取数，转换成插件内部需要的格式：

```
mac,ip,iface,in,out,total,first,last
```

数据链路变成：

```
wechatpush → /usr/libexec/rtbwmon.sh update → usage.db → 流量页面 / 阈值告警
```

`wrtbwmon` 分支原样保留，仅当 `/usr/sbin/wrtbwmon` 确实存在时才走，所以打过补丁的文件在装了 wrtbwmon 的旧系统上同样能工作。

---

## 改动内容

只改 `/usr/share/wechatpush/wechatpush` 一个文件：

**① 依赖自检**（原第 139 行）——`rtbwmon` 或 `wrtbwmon` 任一存在都不再告警：

```diff
-[ ! -f "/usr/sbin/wrtbwmon" ] && log_change "[WARN] ... wrtbwmon not installed ..."
+[ ! -x "/usr/libexec/rtbwmon.sh" ] && [ ! -f "/usr/sbin/wrtbwmon" ] && log_change "[WARN] ..."
```

**② `usage()` 的 update 分支**——优先走 rtbwmon：

```diff
 usage() {
-	[ ! -f "/usr/sbin/wrtbwmon" ] || [ -z "$1" ] && return
+	[ -z "$1" ] && return
 	if [ $1 == "update" ]; then
+		if [ -x "/usr/libexec/rtbwmon.sh" ]; then
+			# 取数 → 过滤 → 归并 → 写 usage.db，然后 return
+		fi
+		# 兼容原 wrtbwmon（仅当其仍存在时）
+		[ ! -f "/usr/sbin/wrtbwmon" ] && return
 		...
```

**③ 文件头插入 GPL-2.0 要求的改动声明**（上游同为 GPL-2.0，见 `LICENSE`）

完整 diff 见 [`patch/wechatpush-rtbwmon.diff`](patch/wechatpush-rtbwmon.diff)。

### 转换时做了三处清洗（都是实测踩出来的）

| 清洗 | 不做的后果 |
|---|---|
| 只保留 `network.lan.device`（通常是 `br-lan`）接口的行 | `docker0` 的容器 IP（172.17.0.x）、`eth0` 的 WAN 地址会混进设备统计 |
| 按 MAC 归并，同 MAC 多行取 `total` 最大的一条 | rtbwmon 是按 **IP** 计数的，同一台设备可能有多条 IP 记录（含 `total=0` 的陈旧 ARP 条目），插件原有 `sort -u \| head -n1` 会取到 **0** |
| 剔除 `total=0` 的行 | 零值污染统计与「超标告警」判断 |

---

## 安装

### 方式 A：直接用现成文件（最省事）

把 [`dist/wechatpush`](dist/wechatpush) 传到路由器后执行：

```sh
scp dist/wechatpush root@192.168.3.1:/tmp/wechatpush.new
ssh root@192.168.3.1
sh /path/to/install.sh /tmp/wechatpush.new
```

或手动：

```sh
cp -a /usr/share/wechatpush/wechatpush /usr/share/wechatpush/wechatpush.bak.$(date +%Y%m%d%H%M%S)
cp -f /tmp/wechatpush.new /usr/share/wechatpush/wechatpush
chmod 755 /usr/share/wechatpush/wechatpush
bash -n /usr/share/wechatpush/wechatpush
/etc/init.d/wechatpush restart
```

> 脚本 shebang 是 `#!/bin/bash`（用了 herestring），**语法校验必须用 `bash -n`**，用 `sh -n`（busybox ash）会误报第 202 行的 herestring 错误。

### 方式 B：对自己的原文件打补丁（推荐给动手党）

```sh
# 先把路由器上的原文件拉到本机
scp root@192.168.3.1:/usr/share/wechatpush/wechatpush ./wechatpush.orig

# 打补丁
python3 patch/patch_wechatpush_rtbwmon.py -s wechatpush.orig -o wechatpush.patched

# 再传回去按方式 A 安装
```

补丁脚本是**严格匹配式**的：匹配不到原文（例如上游改了结构、或版本不是 v3.6.12）会直接报错退出，**不会产出半成品文件**；对已打补丁的文件重复执行也会被识别并拒绝。

### 一键安装脚本

```sh
sh install.sh /tmp/wechatpush.new   # 安装
sh install.sh --restore             # 回滚到最近一次备份
```

`install.sh` 会依次做：检查 bash / rtbwmon 是否存在 → `bash -n` 语法校验 → 备份原文件 → 覆盖 → 重启 wechatpush → 打印 `usage.db` 前几行。

---

## 验证

```sh
# 1. 日志里不该再有 wrtbwmon 警告
tail -20 /tmp/wechatpush/wechatpush.log

# 2. 数据库应该被生成，且有真实设备
cat /tmp/wechatpush/usage.db
# mac,ip,iface,in,out,total,first,last
# 1c:83:41:41:02:ec,192.168.3.100,br-lan,673697,3241711,3915408,1760839,1760839

# 3. 60 秒后 total 应该变大（说明在自动轮询）
```

实测输出示例（4 台 LAN 设备，NAS 在内）：

```
mac,ip,iface,in,out,total,first,last
1c:83:41:41:02:ec,192.168.3.100,br-lan,673697,3241711,3915408,1760839,1760839
d8:cc:98:55:35:68,192.168.3.136,br-lan,243016,317454,560470,1760839,1760839
d4:35:38:73:09:10,192.168.3.133,br-lan,12514,29326,41840,1760839,1760839
```

---

## 回滚

```sh
sh install.sh --restore
# 或手动
cp -f /usr/share/wechatpush/wechatpush.bak.<时间戳> /usr/share/wechatpush/wechatpush
/etc/init.d/wechatpush restart
```

补丁没有修改任何其它文件，也没有安装任何软件包，回滚代价接近于零。

---

## 已知限制

- **别卸载 `luci-app-rtbwmon`**：它提供 `/usr/libexec/rtbwmon.sh` 这个数据源，卸载后流量统计会真失效（但不再报 WARN 之外无副作用）。
- **流量统计功能需要自己启用**：补丁只提供数据源，`wechatpush` 的 `client_usage` 选项仍需在 LuCI 里勾选，`client_usage_max` 控制超标推送。
- **计数特性**：rtbwmon 基于 nft 计数器，按 IP 累计；设备离线后记录不会立刻消失（这也意味着总量只增不减，符合 rtbwmon 自身行为）。
- **只针对 v3.6.12 验证过**：上游脚本结构变动会导致补丁匹配失败——此时脚本会报错而不是产出坏文件，需要自行适配。
- **不适用于完全没装 rtbwmon 的系统**：那时会退回到原来的行为（报 WARN、统计不可用）。

---

## 测试环境

| 项 | 版本 |
|---|---|
| 系统 | iStoreOS 24.10.8 (x86_64)，firewall4 / nftables |
| 插件 | luci-app-wechatpush 3.6.12 |
| 数据源 | luci-app-rtbwmon 1.1.0-1（提供 `/usr/libexec/rtbwmon.sh`） |
| shell | bash 5.2（插件解释器） |

---

## 许可与致谢

本项目遵循 **GPL-2.0**（与上游一致），详见 [`LICENSE`](LICENSE)。

- [tty228/luci-app-wechatpush](https://github.com/tty228/luci-app-wechatpush) —— 被修改的上游项目，GPL-2.0
- [luci-app-rtbwmon](https://github.com/gs10305/rtbwmon-openwrt) —— 提供 nft 原生流量计数数据源
- `dist/wechatpush` 是上游文件的修改版，已在文件头标注改动内容与日期（GPL-2.0 §2a）
