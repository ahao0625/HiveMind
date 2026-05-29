# HiveMind MCP Server

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-1.12%2B-purple)](https://modelcontextprotocol.io)
[English](README.md) | [中文](README_CN.md)

**外置指挥官框架** — AI 负责思考，框架负责把关。

## 这是什么？

每次让 AI 帮你跑个命令、读个文件，你都在赌它不会乱来。你再怎么往 Prompt 里塞「不准」「禁止」也没用——它不仅记不住，Token 还被吃光了。

HiveMind 做一件事：**AI 负责思考，框架负责把关。** 能做什么、不能做什么、做完合不合格，全由外部规则引擎说了算。你点过头的操作记住，下次直接过。不占 Prompt，越用越快。

## 能做到什么？

- 🛡️ **双层注入防御** — 结构层：逐参数校验字符、类型、长度，零误报；语义层：置信度分级（≥95% 硬阻止 / 50-95% 静默降级 / 30-50% 仅日志），攻击者无反馈
- 📊 **智能评分放行** — 读文件自动通过，写文件看情况，删文件严格审批
- 🔍 **事后验证 + 自动回滚** — 执行后校验语法、密钥泄露、结果完整性；验证失败自动从写前快照恢复
- ⚡ **系统 1/2 分流** — 纯读操作走快通道（<10ms），写操作走完整安全 → 执行 → 验证 → 记录流程
- 🧠 **四层记忆** — 工作记忆（单任务隔离）、短期记忆（TTL 缓存）、长期记忆（JSON 持久化）、程序性记忆（环境快照，越用越快）
- 🔄 **失败自动回滚** — 写前自动快照；验证不通过 → 文件自动恢复原状
- 🌐 **SSRF 防护** — 内网 IP 阻止（RFC1918、回环、链路本地、组播、IPv6 私网）+ 重定向逐跳校验
- 📝 **全链路审计** — 谁在什么时候做了什么、被哪层拦截的、最终评分多少，全可追溯

**一句话：让 AI 帮你做事，但别让它乱来。**

---

## 架构

```
MCP Client (Claude / Cursor / ...)
        │
        ▼
┌─ 网关 Gateway ────────────────────────────────────────────────┐
│  认证 → 结构哨兵(逐参数字符/类型/长度)                          │
│       → 语义分类器(置信度：阻止/静默降级/日志)                   │
│       → 令牌桶限流                                            │
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌─ 指挥官 Commander ────────────────────────────────────────────┐
│  意图精炼 → 规则引擎 → 仲裁 → 任务路由                          │
│                                                              │
│  硬性门控: 一票否决   软性评分: 五维度加权                       │
│  系统1 (缓存命中 → 环境校验 → 快通道)                           │
│  系统2 (执行 → 验证管线 → 记录 → 审计)                         │
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌─ 执行器 Executor ─────────────────────────────────────────────┐
│  文件 (沙箱 + 写前快照)                                       │
│  Shell (二进制白名单)                                         │
│  HTTP (域名白名单 + 内网IP阻止 + 重定向校验)                    │
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌─ 验证管线 Verification Pipeline ──────────────────────────────┐
│  语法校验 → 安全规则(密钥泄露扫描) → 结果完整性                  │
│  ┌─ 失败 → 回滚(从快照恢复)                                   │
│  └─ 通过 → 清理快照 + 记录程序性记忆                           │
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌─ 记忆系统 Memory (4层) ───────────────────────────────────────┐
│  工作记忆(单任务) / 短期记忆(TTL) / 长期记忆(JSON)              │
│  程序性记忆(环境快照 → 越用越快)                               │
└──────────────────────────────────────────────────────────────┘
```

### 双层规则引擎

| 层级 | 机制 | 判定 | 举例 |
|------|------|------|------|
| **硬性门控** | 一票否决 | 任一规则不通过 → 立即拒绝 | 禁止 `rm -rf /`、禁止读取 `/etc/passwd` |
| **软性评分** | 加权求和（5 维度） | ≥0.40 自动通过 / 0.40-0.70 需审批 / <0.30 拒绝 | 读操作分高、写操作分低、删操作分最低 |

### 双层注入检测

| 层级 | 类型 | 机制 | 误报率 |
|------|------|------|--------|
| **结构哨兵** | 确定性 | 逐参数分槽校验：字符白名单、类型约束、最大长度 | 零 |
| **语义分类器** | 置信度分级 | ≥95% → 硬阻止 / 50-95% → 静默降级（清洗参数）/ 30-50% → 仅日志 | 极低 |

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
# 预期输出: Results: 79/79 passed, 0 failed
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

> HTTP 请求受域名白名单保护，阻止内网 IP（防 SSRF），重定向逐跳校验。

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

每一笔工具调用经过七道关卡：

1. **认证** — API Key 校验，拒绝未授权请求
2. **结构哨兵** — 逐参数分槽校验：字符白名单、类型约束、长度限制；确定性检测，零误报
3. **语义分类器** — 置信度分级：≥95% 硬阻止 / 50-95% 静默降级（攻击者无反馈）/ 30-50% 仅日志
4. **令牌桶限流** — 每身份独立桶，防止滥用
5. **意图精炼** — 自动评估风险等级（low / medium / high / critical）
6. **规则引擎** — 硬性门控（一票否决）+ 软性评分（五维度加权）
7. **验证管线** — 执行后校验：语法格式 → 密钥泄露扫描 → 结果完整性；失败则从写前快照回滚

### 执行器安全

| 执行器 | 保护措施 |
|--------|----------|
| 文件操作 | 沙箱根目录限制；写前自动快照（验证失败可回滚）；路径遍历阻止 |
| Shell 命令 | 二进制白名单，未知命令拒绝执行 |
| HTTP 请求 | 域名白名单；内网 IP 阻止（RFC1918、回环、链路本地、组播、IPv6 私网）；重定向逐跳校验目标 |

---

## 项目结构

```
HiveMind/
├── pyproject.toml
├── README.md
├── README_CN.md
├── .env.example
├── .gitignore
├── src/hivemind/
│   ├── __init__.py
│   ├── config.py              # 所有 Pydantic 配置模型（v2.0: +6 个新类）
│   ├── context.py             # AppContext 运行时状态
│   ├── server.py              # FastMCP 入口（15 个工具/资源/提示）
│   ├── gateway/
│   │   ├── auth.py            # API Key 认证
│   │   ├── injection.py       # 双层注入检测（v2.0 重构）
│   │   ├── structural_guard.py # v2.0: 逐参数分槽校验
│   │   ├── semantic_classifier.py # v2.0: 置信度攻击分类
│   │   ├── rate_limiter.py    # 令牌桶限流
│   │   └── audit.py           # 审计日志（环形缓冲区）
│   ├── commander/
│   │   ├── intent_refiner.py  # 意图精炼 + 风险分级
│   │   ├── rule_engine.py     # 硬门控 + 软评分引擎
│   │   ├── arbiter.py         # 最终仲裁决策
│   │   ├── task_router.py     # 系统1(快)/系统2(慢) 分流
│   │   ├── state_manager.py   # 任务状态机（v2.0: +回滚+升级状态）
│   │   └── lifecycle.py       # 核心编排器（v2.0: 验证管线+程序性记忆已接入）
│   ├── executors/
│   │   ├── base.py            # 抽象基类
│   │   ├── file_ops.py        # 沙箱文件读写删（v2.0: +写前快照）
│   │   ├── shell_ops.py       # 白名单 Shell 执行
│   │   └── http_ops.py        # 域名白名单 HTTP（v2.0: +SSRF+重定向校验）
│   ├── verification/
│   │   ├── base.py            # 抽象基类
│   │   ├── pipeline.py        # 管线编排器（支持 fail_fast）
│   │   ├── syntax_check.py    # JSON/YAML 语法校验
│   │   ├── security_check.py  # 密钥泄露扫描（v2.0: +read_file +http_* 输出扫描）
│   │   └── result_check.py    # 退出码/完整性检查
│   ├── memory/
│   │   ├── working.py         # 工作记忆（v2.0: max_bytes 淘汰）
│   │   ├── short_term.py      # 短期记忆（TTL 缓存）
│   │   ├── long_term.py       # 长期记忆（v2.0: 原子写入）
│   │   ├── procedural.py      # v2.0: 程序性记忆（环境快照 → 越用越快）
│   │   ├── consistency.py     # v2.0: 跨层一致性管理
│   │   └── facade.py          # v2.0: MemorySystem 统一门面
│   └── observability/
│       ├── logger.py          # structlog / stdlib 双模
│       └── metrics.py         # 计数器/仪表盘/直方图
└── tests/
    ├── verify.py              # 独立验证脚本（79 项检查）
    ├── test_rule_engine.py
    ├── test_gateway.py        # v2.0: +结构哨兵+语义分类器测试
    ├── test_verification.py   # v2.0: +read_file +http_* 输出扫描测试
    ├── test_procedural_memory.py   # v2.0
    ├── test_memory_system.py       # v2.0
    └── test_lifecycle_v2.py        # v2.0
```

---

## 设计原则

- **不可变数据** — 所有 Pydantic 模型 `frozen=True`，只创建不修改
- **宪法即代码** — 规则集通过 JSON 配置，`importlib` 动态加载，无需改源码即可扩展
- **全链路审计** — 网关→仲裁→执行→验证，每步可追溯
- **系统 1/2 分流** — 缓存命中 + 低风险走快通道，高风险走完整验证 → 失败回滚
- **纵深防御** — 双层注入检测（结构+语义）、SSRF 防护、密钥扫描、写前快照
- **原子持久化** — 所有文件写入使用 `tempfile.mkstemp` + `os.replace`，防止写崩溃损坏数据
- **越用越快** — 程序性记忆记录执行结果+环境快照；缓存复用前校验环境一致性，不一致自动降级

---

## 常见问题

### API Key 是什么？我用 Claude 还需要再设一个？

`HIVEMIND_API_KEYS` 不是任何第三方服务的 Key，而是 **HiveMind 自己的门锁密码**。

Claude 的 API Key 是你和 Anthropic 之间的身份凭证，HiveMind 的 Key 是 MCP 客户端和 HiveMind 安检门之间的身份凭证——两把不同的钥匙。

不设也可以，留空跳过认证。设上只是多一层保障，防止不认识的 MCP 客户端连进来操作你的文件。

### 为什么我的命令被拦截了？

HiveMind 有三层拦截：

- **结构哨兵** — 参数中包含非法字符、超长、或类型不匹配。例如路径中含 `;`、文件名 300 字符。
- **硬性门控** — 无条件拒绝。比如 `rm -rf /`、读取 `/etc/passwd`、路径含 `../` 穿越——没商量。
- **软性评分** — 按风险打分。写文件、删文件比读文件分低，低于阈值会被要求人工审批。

如果你确定某个操作是安全的但被误拦了，可以用 `get_constitution` 查看当前规则，然后自定义 `constitution.json` 调整。

### 验证失败会发生什么？

操作会被回滚——文件从写前快照（`.hivemind-bak`）恢复原状。任务标记为失败。不会留下任何不完整或损坏的状态。

### 报错 "ImportError: cannot import name ..."

绝大多数情况是因为 `PYTHONPATH` 没设对。确认在项目根目录执行：

```bash
PYTHONPATH=src python3 -m hivemind.server
#                          ↑ 必须在 HiveMind 根目录执行
```

如果用 pip 安装后命令行启动则不需要设 `PYTHONPATH`：

```bash
pip install git+https://github.com/ahao0625/HiveMind.git
hivemind
```

### structlog 安装不上怎么办？

structlog 是可选依赖，没安装时自动退回到 Python 标准库 `logging`，功能完整可用。只是日志格式从彩色结构化变成普通文本，不影响任何功能。

### FileOpsExecutor 报 PermissionError

默认沙箱目录在 `$TMPDIR/hivemind-sandbox`，某些系统（如 macOS 沙箱）禁止写 `/tmp`。可以手动指定：

```bash
export HIVEMIND_SANDBOX_ROOT="$HOME/.hivemind/sandbox"
```

### 怎么扩展自己的安全规则？

创建 `~/.hivemind/constitution.json`，添加自定义硬性门控或评分维度：

```json
{
  "hard_gates": [
    {
      "id": "custom_rule",
      "name": "我的自定义规则",
      "description": "禁止修改 .env 文件",
      "priority": 50,
      "check_function": "my_module.rules:check_env_file"
    }
  ]
}
```

`check_function` 格式为 `模块路径:函数名`，HiveMind 会通过 `importlib` 动态加载。函数签名：

```python
def check_env_file(intent: RefinedIntent) -> GateResult:
    ...
```

### 怎么看到底发生了什么？

用 `get_audit_trail` 工具查看最近 50 条审计记录，每条包含：时间、调用者、工具名、网关结果、仲裁决定、执行结果、验证结果。

---

## 许可

MIT
