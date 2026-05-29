# HiveMind MCP Server

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-1.12%2B-purple)](https://modelcontextprotocol.io)

**外置指挥官框架** — AI 只有建议权，框架拥有执行权。

## 这是什么？

当你让 AI 「帮我清理一下桌面文件夹」，它可能会执行 `rm -rf ~/Desktop/*`。你让它「查一下这个 API 的返回」，它可能把你的密钥连同请求一起发到了外部服务。

**HiveMind 就是 AI 和你电脑之间的一道安检门。** 每次 AI 想操作你的文件、执行命令、发 HTTP 请求时，HiveMind 会先拦住，问六个问题：

1. 你是谁？（API Key 认证）
2. 你输入里有没有恶意代码？（注入检测）
3. 你是不是太频繁了？（限流）
4. 你想干什么？危险吗？（意图分析）
5. 规则允许你这么做吗？（硬性门控一票否决 + 软性评分）
6. 你执行完的结果安全吗？（验证管线）

## 能做到什么？

- 🛡️ **自动拦截危险操作** — `rm -rf /`、读取 `/etc/passwd`、路径 `../../` 遍历，直接拒绝
- 📊 **智能评分放行** — 读文件自动通过，写文件看情况，删文件严格审批
- 🔍 **事后验证** — 文件写完了检查是不是 JSON 格式错误、有没有不小心写入了密钥
- 📝 **全链路审计** — 谁在什么时候做了什么、结果如何、被谁阻止的，全可追溯
- ⚡ **读写分流** — 纯读操作走快通道（<10ms），写操作走完整安全检查
- 🧠 **三层记忆** — 工作记忆（当前任务）、短期记忆（带过期时间）、长期记忆（持久化）

**一句话：让 AI 帮你做事，但别让它乱来。**

---

## 架构

```
MCP Client (Claude / Cursor / ...)
        │
        ▼
┌─ Gateway ──────────────────────────────────────────┐
│  API Key 认证 → 注入检测(命令/SQL/路径遍历) → 令牌桶限流  │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─ Commander ────────────────────────────────────────┐
│  意图精炼 → 规则引擎(硬门控+软评分) → 仲裁 → 任务路由    │
│                                                   │
│  硬性门控: 一票否决  软性评分: ≥60通过 30-59审批 <30拒绝 │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─ Executor ─────────────────────────────────────────┐
│  文件读写删(沙箱) / Shell命令(二进制白名单) / HTTP(域名白名单) │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─ Verification Pipeline ────────────────────────────┐
│  语法校验 → 安全规则(泄露检测) → 结果完整性              │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─ Memory ───────────────────────────────────────────┐
│  工作记忆(单任务) / 短期记忆(TTL) / 长期记忆(JSON持久化)   │
└────────────────────────────────────────────────────┘
```

### 双层规则引擎

| 层级 | 机制 | 判定 | 举例 |
|------|------|------|------|
| **硬性门控** | 一票否决 | 任一规则不通过 → 立即拒绝 | 禁止删除 `/etc/passwd`、禁止 `rm -rf /` |
| **软性评分** | 加权求和 | ≥60 自动通过 / 30-59 需人工审批 / <30 拒绝 | 读操作分高、写操作分低、删操作分最低 |

---

## 快速开始

### 安装

```bash
# 方式一: pip 安装（推荐）
pip install git+https://github.com/ahao0625/HiveMind.git

# 方式二: 克隆 + 开发模式
git clone https://github.com/ahao0625/HiveMind.git
cd HiveMind
pip install -e ".[dev]"
```

> `structlog` 为可选依赖，未安装时自动退回到 stdlib logging。

### 启动

```bash
# pip 安装后直接使用命令
hivemind

# 或开发模式
PYTHONPATH=src python3 -m hivemind.server
```

### 验证

```bash
PYTHONPATH=src python3 tests/verify.py
# 预期输出: Results: 51/51 passed, 0 failed
```

```bash
pytest tests/ -v
```

---

## MCP 客户端配置

### 方式一：pip 安装后（推荐）

```json
{
  "mcpServers": {
    "hivemind": {
      "command": "hivemind",
      "env": {
        "HIVEMIND_API_KEYS": "your-api-key"
      }
    }
  }
}
```

### 方式二：开发模式

```json
{
  "mcpServers": {
    "hivemind": {
      "command": "python3",
      "args": ["-m", "hivemind.server"],
      "env": {
        "PYTHONPATH": "/path/to/HiveMind/src",
        "HIVEMIND_API_KEYS": "your-api-key"
      },
      "cwd": "/path/to/HiveMind"
    }
  }
}
```

---

## 配置参考

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `HIVEMIND_API_KEYS` | 逗号分隔的 API Key 列表，为空则不认证 | `""` |
| `JSON_LOG` | 设为 `1` 输出 JSON 格式日志（生产环境） | 关闭 |
| `HIVEMIND_CONSTITUTION_PATH` | 自定义规则集配置文件路径 | `~/.hivemind/constitution.json` |

### 宪法规则文件（constitution.json）

可通过 `HIVEMIND_CONSTITUTION_PATH` 指定自定义规则集：

```json
{
  "hard_gates": [
    {
      "id": "no_destructive_commands",
      "name": "禁止破坏性命令",
      "description": "阻止 rm -rf、format 等操作",
      "priority": 100,
      "check_function": "hivemind.commander.rule_engine:check_no_destructive_commands"
    }
  ],
  "scoring_dimensions": [
    {
      "id": "safety",
      "name": "安全性",
      "description": "操作的安全程度",
      "weight": 0.40,
      "score_function": "hivemind.commander.rule_engine:score_safety"
    }
  ],
  "approval_threshold": 0.40,
  "human_approval_threshold": 0.70
}
```

> `check_function` / `score_function` 通过 `importlib` 动态加载，支持自定义扩展。

---

## API 参考

### 工具

#### 文件操作

| 工具 | 参数 | 返回 |
|------|------|------|
| `read_file` | `path: str` | 文件内容 |
| `write_file` | `path: str`, `content: str` | `[OK]` 或 `[VERIFICATION FAILED]` |
| `delete_file` | `path: str` | `[OK]` |
| `list_files` | `path: str` (默认 `"."`) | 文件列表 |

#### Shell

| 工具 | 参数 | 返回 |
|------|------|------|
| `run_command` | `command: str`, `cwd: str?` | stdout + 验证警告 |

> Shell 执行受二进制白名单保护，只允许安全命令。

#### HTTP

| 工具 | 参数 |
|------|------|
| `http_get` | `url: str` |
| `http_post` | `url: str`, `body: str`, `content_type: str` |
| `http_put` | `url: str`, `body: str`, `content_type: str` |
| `http_delete` | `url: str` |

> HTTP 请求受域名白名单保护。

#### 记忆

| 工具 | 参数 | 说明 |
|------|------|------|
| `store_memory` | `key: str`, `value: str` | 存入长期记忆 |
| `recall_memory` | `query: str`, `limit: int` | 搜索记忆（短期+长期） |

#### 可观测性

| 工具 | 说明 |
|------|------|
| `get_constitution` | 查看当前生效的规则集 |
| `get_audit_trail` | 查看最近 50 条审计记录 |
| `get_metrics` | 查看计数器/延迟等指标 |

### 资源

| URI | 内容 |
|-----|------|
| `hivemind://constitution` | 当前规则集 JSON |
| `hivemind://status` | 服务器状态 |

### 提示

| 提示 | 用途 |
|------|------|
| `plan_task` | 引导 AI 规划任务步骤 |
| `review_result` | 引导 AI 审查执行结果 |
| `troubleshoot` | 引导 AI 排查错误 |

---

## 安全模型

每一笔工具调用经过六道关卡：

1. **认证** — API Key 校验，拒绝未授权请求
2. **注入检测** — 命令注入（`; rm -rf /`）、SQL 注入、路径遍历（`../../etc/passwd`）
3. **令牌桶限流** — 每身份独立桶，防止滥用
4. **意图精炼** — 自动评估风险等级（low / medium / high / critical）
5. **规则引擎** — 硬性门控（一票否决）+ 软性评分（加权求和）
6. **验证管线** — 执行后校验：语法格式 → 密钥泄露扫描 → 结果完整性

### 执行器安全

| 执行器 | 保护措施 |
|--------|----------|
| 文件操作 | 限制在沙箱根目录内，禁止遍历逃逸 |
| Shell 命令 | 二进制白名单，未知命令拒绝执行 |
| HTTP 请求 | 域名白名单，禁止请求内网地址 |

---

## 项目结构

```
HiveMind/
├── pyproject.toml
├── README.md
├── .env.example
├── .gitignore
├── src/hivemind/
│   ├── __init__.py
│   ├── config.py              # 所有 Pydantic 配置模型
│   ├── context.py             # AppContext 运行时状态
│   ├── server.py              # FastMCP 入口（15 个工具/资源/提示）
│   ├── gateway/
│   │   ├── auth.py            # API Key 认证
│   │   ├── injection.py       # 注入检测（命令/SQL/路径遍历）
│   │   ├── rate_limiter.py    # 令牌桶限流
│   │   └── audit.py           # 审计日志（环形缓冲区）
│   ├── commander/
│   │   ├── intent_refiner.py  # 意图精炼 + 风险分级
│   │   ├── rule_engine.py     # 硬门控 + 软评分引擎
│   │   ├── arbiter.py         # 最终仲裁决策
│   │   ├── task_router.py     # 系统1(快)/系统2(慢) 分流
│   │   ├── state_manager.py   # 任务状态机
│   │   └── lifecycle.py       # 核心编排器
│   ├── executors/
│   │   ├── base.py            # 抽象基类
│   │   ├── file_ops.py        # 沙箱文件读写删
│   │   ├── shell_ops.py       # 白名单 Shell 执行
│   │   └── http_ops.py        # 域名白名单 HTTP
│   ├── verification/
│   │   ├── base.py            # 抽象基类
│   │   ├── pipeline.py        # 管线编排器（支持 fail_fast）
│   │   ├── syntax_check.py    # JSON/YAML 语法校验
│   │   ├── security_check.py  # API Key/私钥泄露扫描
│   │   └── result_check.py    # 退出码/完整性检查
│   ├── memory/
│   │   ├── working.py         # 工作记忆（单任务隔离）
│   │   ├── short_term.py      # 短期记忆（TTL 缓存）
│   │   └── long_term.py       # 长期记忆（JSON 文件持久化）
│   └── observability/
│       ├── logger.py          # structlog / stdlib 双模
│       └── metrics.py         # 计数器/仪表盘/直方图
└── tests/
    ├── verify.py              # 独立验证脚本（51 项检查）
    ├── test_rule_engine.py
    ├── test_gateway.py
    └── test_verification.py
```

---

## 设计原则

- **不可变数据** — 所有 Pydantic 模型 `frozen=True`，只创建不修改
- **宪法即代码** — 规则集通过 JSON 配置，`importlib` 动态加载，无需改源码即可扩展
- **全链路审计** — 网关→仲裁→执行→验证，每步可追溯
- **系统 1/2 分流** — 缓存命中 + 低风险走快通道（<10ms），高风险走完整 ReAct 验证

## 许可

MIT
