# 配置说明

在 AstrBot 插件页修改配置后，保存并重载插件。

## 配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 启用插件 |
| `enable_favorites` | `true` | 允许搜索和发送收藏表情；关闭时同时停止读取收藏 |
| `enable_market` | `true` | 允许搜索和发送已学习的商城表情 |
| `enable_faces` | `true` | 允许搜索和发送 QQ 原生表情 |
| `enable_unicode` | `true` | 允许 Unicode emoji；关闭时过滤工具文字和正常非流式模型回复中的 emoji |
| `family_priority` | `["favorite", "market", "face", "unicode"]` | 从前到后的类型优先级，跳过关闭的类型，未列出的类型补到末尾 |
| `fallback_to_other_types` | `true` | 首选类型不合适时，允许 AI 考虑其他已启用类型 |
| `face_config_paths` | `[]` | AstrBot 可读取的 QQ `face_config.json` 文件路径列表 |
| `favorite_count` | `1000` | 单次请求收藏数量，范围 1–2000 |
| `admin_only` | `false` | 仅允许 AstrBot 管理员使用插件 |
| `allowed_sessions` | `[]` | 允许的完整 `unified_msg_origin` 列表；空列表沿用 AstrBot 的会话范围 |
| `max_per_turn` | `1` | 每轮表情发送尝试次数，范围 1–3 |
| `cooldown_seconds` | `2.0` | 同一会话两次表情发送尝试的最小间隔，单位为秒 |
| `tool_guidance` | `true` | 在当前模型请求中加入工具使用和类型策略说明 |
| `describe_incoming` | `true` | 向模型补充本条消息中原生、商城表情的元数据 |

同步、学习和删除学习记录始终需要管理员权限。类型开关作用于目录搜索和发送校验，关闭类型后，已有缓存和手动指令也不能发送该类型。

## QQ 资源文件

`face_config_paths` 中的路径必须能被 **AstrBot 进程**读取。Linux QQ 的文件通常位于 QQ 用户数据目录下：

```text
global/nt_data/Emoji/emoji-resource/face_config.json
```

Docker 部署可将资源目录只读挂载至 AstrBot。以下示例假定宿主机的 QQ 数据位于 `./ntqq`：

```yaml
services:
  astrbot:
    volumes:
      - ./data:/AstrBot/data
      - ./ntqq/global/nt_data/Emoji/emoji-resource:/qq-emoji-resource:ro
```

对应插件配置：

```json
{
  "face_config_paths": ["/qq-emoji-resource/face_config.json"]
}
```

QQ 更新资源后，执行 `/qqemoji sync`。若 QQ 目录中的 ID 尚未被当前 NapCat 版本支持，发送可能失败。

也可使用[导出工具](../tools/export_qq_faces.py)校验并复制资源 JSON：

```bash
python tools/export_qq_faces.py /path/to/face_config.json /shared/qq-face-config.json
```

目标文件须不存在，其父目录须已存在。将目标文件在 AstrBot 中的路径填入配置；QQ 资源更新后需重新导出。

未设置资源路径时，收藏读取和原生、商城表情学习仍可使用。

## 优先级与回退

`family_priority` 的类型值为：

| 值 | 类型 |
| --- | --- |
| `favorite` | QQ 收藏表情 |
| `market` | 商城表情 |
| `face` | QQ 原生表情 |
| `unicode` | Unicode emoji |

开启 `fallback_to_other_types` 时，AI 可按顺序考虑其他类型，也可不发表情。关闭后，AI 搜索与发送接口仅允许第一种已启用类型；无合适候选时使用文字回复。手动 `/qqemoji list` 和 `/qqemoji send` 可指定其他已启用类型。

优先级控制候选顺序和可用类型，候选是否适合语境由模型判断。

## 消息布局与发送结果

Unicode 与随附文字同条发送。原生、商城和收藏表情独立发送；有随附文字时，先发送文字，再发送表情。该组合计为一次表情发送尝试，超时也计入次数。

| 结果 | 含义 |
| --- | --- |
| `sent` | 所有消息均取得 NapCat 的确认 ID |
| `partial_or_uncertain` | 文字已确认，表情发送失败或结果不确定 |
| `error_or_uncertain` | 操作失败或无法确认；文字未确认时不继续发送表情 |
| `already_attempted` | 当前轮次已尝试相同调用，不重复执行 |

禁用 Unicode 时，过滤范围包括工具随附文字、正常非流式模型回复和对应结果消息链。禁用跨类型回退且首选不是 Unicode 时，AI 普通文字同样不使用 Unicode emoji。用户输入、历史消息、其他插件直接发送的内容及已发出的流式片段不在过滤范围内。

## 数据存储

缓存位于 `data/plugin_data/astrbot_plugin_qq_native_emoji/`，按平台实例和机器人账号隔离。学习记录另按会话隔离；删除学习记录不修改 QQ 收藏夹。收藏在发送前重新读取。

缓存包含收藏资源地址和商城表情 key，应按私有数据管理。Unix 文件权限为 `0600`。模型搜索结果仅提供 ID、类型和名称，表情描述作为不可信数据处理。
