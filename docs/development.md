# 开发说明

## 项目结构

```text
main.py                 AstrBot 生命周期、指令与 AI 工具
metadata.yaml           插件元数据
_conf_schema.json       配置定义
native_emoji/
  catalog.py            QQ 资源解析和目录存储
  policy.py             使用倾向、类型开关、优先级和 Unicode 策略
  service.py            NapCat 接口调用和消息发送
tests/                  单元测试和 SDK 检查
tools/export_qq_faces.py QQ 资源 JSON 导出工具
```

## 本地检查

```bash
python -m pip install -r requirements-dev.txt
ruff check .
ruff format --check .
python -m unittest discover -s tests -v
```

GitHub Actions 在 Python 3.10 和 3.12 上执行上述检查。测试数据为虚构数据，OneBot 调用使用测试替身。

安装 AstrBot SDK 后，可额外检查工具注册、处理函数和消息过滤钩子：

```bash
PYTHONPATH=/path/to/AstrBot python tests/sdk_smoke.py
```

SDK 检查在独立进程运行，不连接实际 QQ 会话。协议参数与客户端显示的验证见[验收清单](acceptance.md)。

## 参考资料

- [AstrBot 插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)
- [AstrBot 官方插件模板](https://github.com/Soulter/helloworld)
- [AstrBot AI 工具接口](https://docs.astrbot.app/dev/star/guides/ai.html)
- [NapCat 消息转换](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-onebot/api/msg.ts)
- [NapCat 收藏表情接口](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-onebot/action/extends/CustomFace.ts)
- [NapCat 原生消息服务类型](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-core/services/NodeIKernelMsgService.ts)
