# QQ 原生表情适配

基于 NapCat OneBot v11 的 AstrBot 插件，提供 QQ 原生表情、Unicode emoji、商城表情和收藏表情的目录搜索与发送功能。

## 功能

| 类型 | 目录来源 | 发送格式 |
| --- | --- | --- |
| QQ 原生表情 | QQ `face_config.json` 中的 `sysface`，或手动学习的消息 | `face` |
| Unicode emoji | QQ `face_config.json` 中的 `emoji` | Unicode 文本 |
| 商城表情 | 管理员学习的原始商城表情消息 | `mface` |
| 收藏表情 | 当前账号的 `fetch_custom_face_detail` 接口 | `image`，`sub_type=1` |

- 四类表情可独立启用，支持类型优先级和跨类型回退设置。
- 支持 0—100 的表情使用倾向，调整 AI 在聊天中使用表情的意愿。
- 提供 AI 搜索、发送工具，以及目录管理指令。
- Unicode 可与文字同条发送；其他表情独立发送，附带文字时先发文字。
- 支持每轮次数限制、会话限频、重复调用拦截及部分发送结果反馈。
- 目录按平台实例和 QQ 账号隔离，学习记录限定当前会话使用。

## 运行要求

- AstrBot `>=4.29.1,<5`。
- 使用 `aiocqhttp` 适配器连接 NapCat OneBot v11。
- 收藏功能需要 NapCat 支持 `fetch_custom_face_detail`；已验证版本为 `4.18.41`。
- AI 自动使用表情需要模型支持工具调用。

本插件适用于 QQ 个人号的 OneBot 接入，不适用于 QQ 官方机器人开放平台适配器。

## 安装

1. 在 AstrBot 插件页选择通过仓库链接安装：

   ```text
   https://github.com/lociere/astrbot_plugin_qq_native_emoji
   ```

2. 在插件配置中设置表情开关、使用倾向与优先级。
3. 如需按名称搜索 QQ 原生表情，设置 `face_config_paths`，详见[配置说明](docs/configuration.md#qq-资源文件)。
4. 保存配置并重载插件，使用管理员账号发送 `/qqemoji sync`。
5. 若人格配置了工具白名单，加入 `qq_native_emoji_search` 和 `qq_native_emoji_send`。

插件通过当前 OneBot 连接访问 NapCat，无需单独配置 WebUI 凭据或 HTTP 服务。

## 指令

| 指令 | 权限 | 用途 |
| --- | --- | --- |
| `/qqemoji status` | 使用者 | 查看目录状态、接口能力和当前策略 |
| `/qqemoji sync` | 管理员 | 重新读取 QQ 资源与收藏 |
| `/qqemoji list [类型] [关键词]` | 使用者 | 搜索目录，最多返回 30 项 |
| `/qqemoji send <表情ID>` | 使用者 | 向当前会话发送指定表情 |
| `/qqemoji learn [名称]` | 管理员 | 学习当前消息或引用消息中的原生、商城表情 |
| `/qqemoji forget <表情ID>` | 管理员 | 删除当前会话的学习记录 |

类型可选 `all`、`favorite`、`market`、`face`、`unicode`。例如：

```text
/qqemoji list favorite
/qqemoji list face 微笑
/qqemoji send face:14
```

学习商城表情时，回复原始表情消息并发送 `/qqemoji learn 名称`。可用指令同时受 `admin_only` 和 `allowed_sessions` 配置约束。

## AI 工具

| 工具 | 用途 |
| --- | --- |
| `qq_native_emoji_search` | 按关键词和类型搜索，返回表情 ID、名称、分类及当前策略 |
| `qq_native_emoji_send` | 根据目录 ID 向当前会话发送，可附带文字 |

默认优先级为 **收藏 → 商城 → QQ 原生 → Unicode**。搜索结果按类型优先级排序；模型根据上下文选择候选，没有合适表情时可直接回复文字。关闭跨类型回退后，AI 仅能搜索和发送第一种已启用类型。

`emoji_desire` 默认为 **50**，数值越高，模型越积极考虑贴切的表情；数值表示表达倾向，不是每条消息的发送概率。设为 **0** 时，AI 自动搜索和发送关闭，正常非流式回复也过滤 Unicode emoji；手动指令仍可使用已启用类型。详细档位与边界见[配置说明](docs/configuration.md#表情使用倾向)。

发送工具返回每条消息的确认 ID。文字已确认、表情发送失败或超时时，返回部分发送结果，供模型避免重复文字和自动补发。

## 功能边界

- 商城表情通过学习原始消息获取，目前不支持完整枚举账号已购商城目录。
- 收藏接口的返回数量受 QQ 限制；目录状态中的截断提示不代表完整性保证。缺少可发送信息的收藏项会被跳过。
- 原生动画、结果参数和商城表情可用性取决于 QQ、NapCat 版本及账号权限。
- 禁用 Unicode 会过滤工具文字和正常非流式模型回复；已发送的流式片段及其他插件直接发送的消息不受此过滤控制。
- 消息 ID 表示 NapCat 已确认操作，客户端显示效果需单独验证。

## 文档

- [配置说明](docs/configuration.md)：完整配置项、资源挂载、发送策略与数据存储。
- [开发说明](docs/development.md)：项目结构、测试命令与参考资料。
- [验收清单](docs/acceptance.md)：QQ 客户端功能验证。

## 许可

代码采用 [MIT License](LICENSE)。QQ 表情素材和商标归相应权利人所有，本仓库不包含 QQ 表情素材。
