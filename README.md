# Markdown Link Checker

一个自包含的 Markdown 文档链接检查 API：客户端提交一组带路径的 Markdown 文件，服务解析标题锚点、相对路径与显式 fragment，按规范化路径解析跨文件引用并输出诊断。结果持久化在 SQLite 中，可按检查 ID 查询。除 Python 依赖外无任何外部服务（无网络校验、无外部数据库）。

## 诊断类型

| 类型 | 含义 |
| --- | --- |
| `missing_target` | 链接目标不存在：目标文件不在提交集合中，或文件存在但 `#fragment` 锚点不存在 |
| `duplicate_anchor` | 同一文件内多个标题生成了相同的锚点（按 GitHub 规则后续标题会得到 `-1`、`-2` 后缀） |
| `path_escape` | 相对路径经规范化后越出提交的文档根（如 `../../secret.md`） |
| `self_reference` | 自循环引用：链接指向文件自身，或指向链接所在章节自己的锚点 |

每条诊断都包含：`source`（来源文件）、`line`（1 起始行号）、`link`（文档中原始写法，可复现）、`resolved`（规范化后的目标路径，可空）和 `message`。

## 快速开始

### Docker Compose（一键启动）

```bash
docker compose up --build
```

服务监听 <http://localhost:8000>，交互式文档在 <http://localhost:8000/docs>。SQLite 数据库保存在名为 `linkcheck-data` 的卷中（容器内路径 `/data/linkcheck.db`）。

### 本地运行

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

数据库路径由环境变量 `LINKCHECK_DB` 控制，默认 `./linkcheck.db`。

## API 使用

### `POST /checks` — 提交文件集合并执行检查

```bash
curl -s -X POST http://localhost:8000/checks \
  -H 'Content-Type: application/json' \
  -d '{
    "files": [
      {"path": "README.md", "content": "# Project\n\nSee the [guide](docs/guide.md#usage) or [gone](docs/nope.md).\n[loop](README.md)\n"},
      {"path": "docs/guide.md", "content": "# Guide\n\n## Usage\n## Usage\n\nBack to [home](../README.md#project).\n[bad](#nope)\n"}
    ]
  }'
```

响应（`201 Created`）：

```json
{
  "check_id": "9f2c1e4a7b8d4f01",
  "created_at": "2026-09-18T12:00:00.000000+00:00",
  "file_count": 2,
  "diagnostic_count": 4,
  "summary": {
    "missing_target": 2,
    "duplicate_anchor": 1,
    "path_escape": 0,
    "self_reference": 1
  },
  "diagnostics": [
    {
      "type": "missing_target",
      "source": "README.md",
      "line": 3,
      "link": "docs/nope.md",
      "resolved": "docs/nope.md",
      "message": "target file not found: 'docs/nope.md'"
    },
    {
      "type": "self_reference",
      "source": "README.md",
      "line": 4,
      "link": "README.md",
      "resolved": "README.md",
      "message": "link points to the file itself"
    },
    {
      "type": "duplicate_anchor",
      "source": "docs/guide.md",
      "line": 5,
      "link": "#usage",
      "resolved": "docs/guide.md",
      "message": "duplicate anchor '#usage' (first defined at line 3); this heading is reachable as '#usage-1'"
    },
    {
      "type": "missing_target",
      "source": "docs/guide.md",
      "line": 8,
      "link": "#nope",
      "resolved": "docs/guide.md#nope",
      "message": "anchor '#nope' not found in 'docs/guide.md'"
    }
  ]
}
```

提交的路径会先规范化（`\` → `/`、折叠 `.`/`..`、去前导 `/`）；规范化后重复或越出根目录的路径会被 `422` 拒绝。

### `GET /checks/{check_id}` — 按检查 ID 查询结果

```bash
curl -s http://localhost:8000/checks/9f2c1e4a7b8d4f01
```

返回与 `POST /checks` 相同的结构；ID 不存在时返回 `404`。

### 其他端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/checks?limit=50` | 最近的检查列表（仅摘要，不含诊断明细） |
| `GET` | `/health` | 健康检查 |

## 解析与解析规则

- **锚点（GitHub 风格）**：标题去掉行内标记后转小写，标点删除，空白字符逐个替换为 `-`，保留字母/数字/下划线/连字符及 CJK 字符。例如 `## 使用方法（推荐）` → `#使用方法推荐`，`# Foo_Bar!` → `#foo_bar`。重名标题依次获得 `-1`、`-2` 后缀（同时产生 `duplicate_anchor` 诊断）。
- **fragment 匹配**：链接中的 fragment 经百分号解码后与目标文件的锚点**精确**匹配（区分大小写），与 GitHub 行为一致——`#Usage` 匹配不到锚点 `usage`。
- **路径解析**：链接路径经百分号解码后相对来源文件所在目录拼接并规范化；以 `/` 开头视为相对文档根；规范化后越出根目录即 `path_escape`。
- **不校验的目标**：带 URI scheme 的链接（`https:`、`mailto:` 等）与协议相对链接（`//host/...`）视为外部链接，离线环境下不校验；图片 `![alt](src)` 与占位符 `#` 也跳过。
- **支持的链接写法**：行内链接 `[text](dest "title")`、尖括号目标 `[text](<my file.md>)`、引用式链接 `[text][label]` / `[label][]` / 快捷引用 `[label]`（label 须在文件内有定义）。
- **忽略的内容**：围栏代码块、行内代码、YAML front matter、脚注 `[^1]`。

## 已知限制

- 仅支持 ATX 标题（`# ...`），不支持 setext 标题（`===` / `---` 下划线式）。
- 行内解析是启发式的：不支持跨行链接目标、链接文本中的嵌套方括号；4 空格缩进代码块不视为代码。
- SQLite 单写入者，默认单 worker 运行；如需多副本部署请共享数据卷或自行扩展存储层。

## 运行测试

```bash
pip install -r requirements-dev.txt
pytest
```

## 项目结构

```
app/
  main.py     # FastAPI 路由与请求校验
  checker.py  # 路径规范化、跨文件解析、诊断生成
  parser.py   # Markdown 标题/锚点/链接解析（GitHub 风格 slug）
  db.py       # SQLite 存取层
  models.py   # Pydantic 请求/响应模型
tests/        # pytest：解析器、检查器、API 三层测试
Dockerfile
docker-compose.yml
```
