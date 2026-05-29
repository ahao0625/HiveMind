# HiveMind MCP Server

外置指挥官框架 (External Commander Framework) —— AI 只有建议权，框架拥有执行权。

## 架构

```
Gateway（认证→注入检测→限流）
  → Commander（意图精炼→规则引擎→仲裁→任务路由）
    → Executor（文件/Shell/HTTP 沙箱执行）
      → Verification（语法→安全→结果完整性）
        → Memory（工作→短期→长期三分层记忆）
```

### 双层规则引擎

| 层 | 机制 | 行为 |
|----|------|------|
| 硬性门控 | 一票否决 | 任何一条规则不通过，立即拒绝 |
| 软性评分 | 加权求和 | ≥60 自动通过 / 30-59 需人工审批 / <30 拒绝 |

## 快速开始

### 安装

```bash
git clone <repo-url> && cd HiveMind
pip install -e ".[dev]"
```

> structlog 为可选依赖，未安装时自动退回到 stdlib logging。

### 启动

```bash
PYTHONPATH=src python3 -m hivemind.server
```

### 运行验证

```bash
PYTHONPATH=src python3 tests/verify.py
```

## MCP 配置

```json
{
  "mcpServers": {
    "hivemind": {
      "command": "python3",
      "args": ["-m", "hivemind.server"],
      "env": {
        "PYTHONPATH": "/Users/ahao/Desktop/HiveMind/src",
        "HIVEMIND_API_KEYS": "your-api-key"
      }
    }
  }
}
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `HIVEMIND_API_KEYS` | 逗号分隔的 API Key 列表 | `""` （无认证） |
| `HIVEMIND_ROOT_DIR` | 文件操作沙箱根目录 | `$TMPDIR/hivemind-sandbox` |

## 工具列表

| 工具 | 描述 | 风险 |
|------|------|------|
| `read_file` | 读取沙箱内文件 | 低 |
| `write_file` | 写入文件 | 高 |
| `delete_file` | 删除文件 | 高 |
| `list_files` | 列出目录 | 低 |
| `run_command` | 白名单 Shell 命令 | 严重 |
| `http_get` / `http_post` / `http_put` / `http_delete` | HTTP 请求 | 中 |
| `store_memory` / `recall_memory` | 记忆存取 | 低 |
| `get_constitution` | 查看规则集 | 低 |
| `get_audit_trail` | 查看审计日志 | 低 |
| `get_metrics` | 查看指标 | 低 |

## 项目结构

```
src/hivemind/
├── config.py           # Pydantic 配置模型 + 宪法规则
├── context.py          # AppContext 运行时状态
├── server.py           # FastMCP 入口
├── gateway/            # 安全网关：认证、注入检测、限流、审计
├── commander/          # 指挥官：意图精炼、规则引擎、仲裁、状态机、任务路由、生命周期
├── executors/          # 执行器：文件操作、Shell 命令、HTTP 请求
├── verification/       # 验证管线：语法、安全、结果完整性
├── memory/             # 三分层记忆：工作记忆、短期记忆、长期记忆
└── observability/      # 日志、指标
```

## 设计原则

- **不可变数据**：所有模型 `frozen=True`，只创建新对象，不修改现有对象
- **沙箱执行**：文件限制根目录、Shell 二进制白名单、HTTP 域名白名单
- **全链路审计**：每次调用记录网关→仲裁→执行→验证全链路
- **系统1/2 分流**：缓存命中 + 低风险走快通道，写操作 + 高风险走完整验证

## 许可

MIT
