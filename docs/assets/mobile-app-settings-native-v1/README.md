# 移动端原生设置

此目录图片是设置页的构图参考，不是当前界面的截图或验收证明。控件实现和功能入口以当前代码为准；图片中的旧 Work／Version／Volume 管理动作与中间管理索引页不适用。

## 当前入口

KMP 的 `settingscenter/domain/SettingsCenterCatalog.kt` 定义设置入口与权限投影；`personalsettings` 和 `administrativesettings` 提供类型化应用契约与网络适配器。
Android 的 `features` 与 iOS 的 `Features/AdministrativeSettings` 使用原生页面、表单和对话框实现操作，不以 Web 设置页替代。

当前设置能力包含账户、语言、Kindle／邮件、用户与访问范围、书库来源与导入、整理与元数据、OPDS、备份、健康检查与日志。可见入口依赖服务端授权，不能因为参考图上有按钮就启用对应操作。稳定端点和字段由当前 repository 适配器维护，本页不复制 API 清单。

## 图片用途

| 图片 | 构图主题 |
| --- | --- |
| `01-account-core.png` | 账户、资料、安全与退出 |
| `02-language-email-kindle.png` | 语言、邮件与 Kindle |
| `03-kindle-queue-users.png` | 发送队列与用户 |
| `04-library-imports.png` | 来源目录与导入 |
| `05-organize-metadata.png` | 整理与元数据 |
| `06-opds-data-tab-order.png` | OPDS、备份与详情设置 |
| `07-health-logs-about.png` | 健康、日志与关于 |
| `08-recognition-categories-provider.png` | 识别、分类与来源配置 |
| `09-management-source-access.png` | 来源编辑和访问范围 |

原生控件、颜色、字号与行度量复用当前组件及生成视觉 token，不从图中采样。表单明确保存，破坏性操作使用对象明确的确认；请求支持取消和过期结果拒绝。系统选择器与分享界面拥有文件／照片交互。

验收覆盖两端物理设备、zh-CN／en-US、深浅色、大字体、权限失效、取消、错误与成功状态。具体执行入口见[手工验收](../../manual-acceptance.md)。
