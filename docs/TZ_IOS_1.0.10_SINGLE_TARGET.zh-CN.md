# TZ iOS 1.0.10 纯单体发行基线

## 固定架构

- 安装包只包含主程序 `com.tianze.tz`，不包含任何 `.appex` 或 Watch App。
- 主程序数据固定写入自身沙盒 `Library/Application Support/com.tianze.tz/telegram-data`。
- 主程序不调用 App Group 容器，后台 `URLSession` 也不设置共享容器。
- 构建不申请 App Group、APNs、Associated Domains 或其他受限 Apple entitlement。
- Release IPA 删除所有 Mach-O 签名，但保留主程序唯一一份
  `embedded.mobileprovision` 模板，供签名平台替换并完整签名。

这不是运行时自动降级方案。1.0.10 没有 App Group 代码路径，也不会根据签名结果切换存储位置。

## 被移除的系统集成功能

- 系统分享扩展
- Notification Service / Notification Content 扩展和远程推送
- Widget
- Siri Intents
- ReplayKit 屏幕广播上传扩展
- Watch App
- 外部网页通过 Universal Links 自动唤起 App

App 内登录、聊天、收发消息、联系人、群组、文件与媒体、语音/视频通话的前台流程仍属于主程序。
`tz://` URL Scheme 仍保留；`tg.tianze8.cc` 链接仍可由 App 内部链接解析逻辑处理。

## 发布门禁

GitHub Actions 只有在以下检查全部通过后才上传 IPA：

1. Bundle ID、版本、品牌、简体中文默认语言正确。
2. gramsrv 的 DC2 地址、端口和 RSA 公钥静态匹配。
3. IPA 中恰好一个主 App，扩展集合为空，Watch 目录不存在。
4. 所有可执行文件包含 arm64，不含模拟器或旧设备架构。
5. 主程序签名权限不含 App Group、APNs、Associated Domains 和其他受限权限。
6. 无签名发行包中所有 Mach-O 的 `LC_CODE_SIGNATURE` 已删除。
7. 无签名发行包恰好保留一份主程序描述文件模板。

## 签名平台要求

签名平台必须：

- 保持 Bundle ID 为 `com.tianze.tz`；
- 替换 `embedded.mobileprovision`，不能沿用仓库中的自签模板；
- 对主程序、所有 Framework 和嵌套 Mach-O 完整签名；
- 保证 Info.plist、签名权限和二进制签名中的 Bundle ID 一致；
- 不向包内重新加入 App Group 权限或扩展。

## 真机验收

静态构建不能代替真机验收。签名后至少检查：首次启动不是黑屏、账号密码登录、重启后账号仍在、
文字和媒体收发、文件下载与上传、App 内打开公开链接、前台来电与通话。远程推送、系统分享、
Widget、Siri、屏幕广播、Watch 和 Universal Links 不在本版本能力范围内。
