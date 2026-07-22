# TZ iOS / GitHub macOS 构建阶段记录

状态日期：2026-07-22（Asia/Shanghai）

## 当前真相

- 官方上游：`TelegramMessenger/Telegram-iOS`。
- 默认分支：`master`。
- 锁定提交：`6ad963e5b62d354da79040f388ae2b9132fb17b8`。
- 上游版本约束：macOS 26、Xcode 26.2、Bazel 8.4.2（下载 SHA256 已写入 `TZ_UPSTREAM.lock`）。
- 本地 Windows 工作树只完成源码检出；13 个 gitlink 未在本机递归初始化，未执行且不能执行 Xcode/Bazel iOS 构建。
- GitHub 官方 `macos-26` 是 arm64 runner image，包含 `/Applications/Xcode_26.2.app`，因此基础环境匹配；磁盘、时间和 Telegram-iOS 全量编译是否足够仍必须由真实 Actions run 证明。
- 当前没有远端 `tz-ios` 仓库，没有 Actions run，没有 artifact，没有 IPA，更没有安装/运行验收。

## 许可证阻塞

锁定提交根目录没有 `LICENSE`/`COPYING`，GitHub 仓库元数据没有 SPDX 标识，GitHub License API 返回 404。README 要求修改者发布自己的代码，但这不是一份完整、可识别的许可证文本。任何对外分发前必须完成来源、历史版本及各子模块许可证的法律审查；不能仅凭 README 一句话推断授权范围。

## Workflow 的边界

`.github/workflows/tz-ios-macos-build.yml` 是目标方案，尚未在 GitHub 运行。它：

1. 只允许在 private repository 手工触发；`contents: read`，不会建 tag 或 Release。
2. 锁定 `macos-26`、Xcode 26.2、Bazel 8.4.2、上游基线 SHA 与三个官方 action 的精确 commit。
3. 递归检出并核对所有 submodule gitlink。
4. API ID/hash 与期望 endpoint 只从 Actions secrets 读取，先 mask，不写仓库、不输出原值；临时 JSON 写到 runner temp 且权限为 0600。
5. 用上游公开的自签证书和伪 profile 构建 `release_arm64`；临时 bundle/team 身份仅为兼容这些伪 profile，不是 TZ 长期身份。
6. 构建失败时从完整 step log 提取第一条具体错误；不把后续 Bazel 汇总错误当根因。
7. 只有 IPA 结构、主 app 和全部扩展 arm64、版本 1.0.1、品牌 TZ、endpoint 静态存在、伪签证书、SHA256 全部通过后才保存工具 cache 并上传 artifact。
8. artifact 名和包内说明都标记 `REQUIRES-FULL-RESIGN`；明确不是 Release、不可直接安装，安装与运行未执行。

当前源码的 `versions.json` 仍为上游 12.9.2，所以 workflow 的 1.0.1 前置门禁会失败。这是故意的真实性门禁：品牌/版本/endpoint 源码改造完成前，不允许产生看似 TZ 1.0.1 的候选 artifact。

## Cache 可验证性与秘密边界

- 不缓存 Bazel 编译输出，因为其中可能包含 API hash、endpoint 或其他私有编译常量。
- 只缓存上游下载的 Bazel 8.4.2 可执行文件；key 包含 runner OS/arch、版本和上游给出的完整 SHA256。
- restore 后再次计算 Bazel 文件 SHA256，并核对 `bazel --version`；workflow 记录 `cache-hit`、Bazel 与 `versions.json` SHA256。
- 仅当 build 与全部 IPA 静态门禁成功后才保存 cache。
- cache 命中只表示精确 Bazel 工具曾被恢复，绝不表示源码、编译或 IPA 已完成。

## 完整重签所需身份与能力

长期 Bundle ID 与 Team ID 尚未确定。确定后必须为主 app 和每个启用扩展创建匹配的 identifier/profile，并保持嵌套关系：

| 目标 | Bundle ID 后缀 | 关键要求 |
|---|---|---|
| 主 app | 无 | App Groups；如需远程通知则启用 Push Notifications/APS；keychain access group；最终 distribution profile |
| Share | `.Share` | 与主 app 相同 App Group 和 Team 前缀，否则分享扩展无法访问共享账号/媒体数据 |
| Notification Content | `.NotificationContent` | 独立 extension profile；通知内容扩展能力与 App Group 一致 |
| Notification Service | `.NotificationService` | 独立 extension profile；APS 由主 app 承担；若保留 communication/filtering 等受限 entitlement，开发者账号必须获批，否则必须从源码 entitlement 中移除 |
| Widget | `.Widget` | 独立 extension profile；App Group 一致 |
| Siri Intents | `.SiriIntents` | 若启用 Siri，App ID/profile 必须包含 Siri entitlement；当前临时配置关闭 Siri |
| Broadcast Upload | `.BroadcastUpload` | 独立 extension profile；App Group 一致；涉及 ReplayKit 屏幕广播 |
| Watch app（当前未嵌入） | `.watchkitapp` 与 `.watchkitapp.watchkitextension` | 若以后启用，两个独立 profile、匹配 Team/App Group/companion ID；不能只重签主 iOS app |

此外，官方 bundle 条件下源码会加入 Apple Pay merchant、unrestricted PushKit VoIP、CarPlay messaging、associated domains、communication/filtering notifications、Sign in with Apple、后台 GPU 等受限 entitlement。TZ 长期身份通常不能直接继承这些授权：必须逐项决定“申请并配置”或“从 TZ build 中删除/关闭”，再为主 app 与所有 `.appex` 自内向外重签，替换每个 `embedded.mobileprovision`，最后重签容器 app。只重签 `Payload/*.app` 外壳会得到形式正确但安装或扩展启动失败的 IPA。

推送还要求与最终 Bundle ID/environment 匹配的 APNs capability、provider 凭据与服务端推送链路；重签本身不会让推送自动工作。App Groups 名必须从当前伪值迁移为最终 `group.<bundle-id>`，客户端所有共享容器引用和全部 profiles/entitlements 必须一致。

## 私有远端的精确计划（尚未获准执行）

1. 总控再次确认仓库 owner/name、长期可见成员和计费边界。
2. 创建 `private` 仓库，创建后立即用 API 再核验 `private=true`；若不是 private，停止且不 push。
3. 禁用 fork、Pages、public Actions 日志暴露路径，设置最小 Actions permissions；是否允许第三方 actions 由总控决定。
4. 只 push 当前本地分支和必要源码；先用 secret scan 检查 API ID/hash、endpoint、证书、profile、token、session 等。
5. API ID/hash、期望 endpoint 进入 Actions secrets；不在 issue、commit message、workflow input 或 step summary 中出现。
6. 首次 run 仅手工触发；queued/in_progress 不报告成功。只有 `completed + success` 后再通过 API 核对 artifact ID/name/size/expiry，并实际下载复核 SHA256。
7. 首次包仍只报告“待完整重签候选”。未在真机安装和运行时，永远披露未执行。

创建远端、写 secrets、触发 Actions 都是外部状态变更；当前阶段均未执行，必须等待总控再次确认。

## 阻塞清单

- TZ iOS 品牌、版本 1.0.1 与私有 endpoint 的源码改造尚未完成。
- Bundle ID、Team ID、App Group、URL scheme 的长期身份未定。
- Apple Developer 账号、证书、主 app 与 6 个扩展 profiles、APNs/associated domains 等能力未准备。
- 上游根许可证不明确，分发前需法律审查。
- 上游伪 profiles 于 2026-10-30 过期，只适合当前可复现构建窗口。
- GitHub private 仓库尚未获准创建，Actions 尚未运行，macOS runner 的磁盘/时长可行性尚无实跑证据。
- 未执行 IPA 下载复核、重签、真机安装、启动、登录、消息、推送、分享扩展或更新链路验证。
