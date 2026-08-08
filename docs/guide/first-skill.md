# 创建第一个 Skill

本章目标：建一个最小 Skill，理解它怎么约束 Agent「按你们业务办事」。

前提：已按 [快速上手](quick-start.md) 能对话。概念全文见 [Skill](../core-concepts/skill.md)；更长模板见 [编写 Skill](../usage/write-skill.md)。

---

## Skill 是什么

**Skill = 给 Agent 的领域规程（Markdown）**，不是业务代码，也不会替你的后端落库。

分工可以这样理解：

- **OpenAPI / Swagger** — 能调什么（接口进 MCP）
- **Skill** — 该怎么调、先做什么、禁止什么
- **企业后端** — 真正落库、算账、鉴权

Runtime 不会执行 Skill 里的脚本。Agent 先看到 **name + description 名片**，需要细则时再 `read_skill`，然后仍靠 MCP 调真实 API。

仓库里已有参考：`account-access`、`select-before-act`。本章自己写一个更短的练习用 Skill。

---

## 目录约定

```text
skills/
  <skill-id>/          # 目录名 = Skill id（read_skill 推荐用这个）
    SKILL.md           # 必填：YAML frontmatter + Markdown 正文
```

- 只扫描 `skills/<一层目录>/SKILL.md`，不要嵌成 `skills/foo/bar/SKILL.md`
- `skills/README.md` 只给人看，不会注入模型
- 事件用的 `skills/events/` 是另一套约定，本章先不管 → [事件 Webhook](../advanced/webhook.md)

配置一般不用改：

```yaml
skills_dir: skills
skills_exclude: [] # 按目录名排除；需要时再填
```

---

## 步骤 1：建目录与文件

在仓库根目录：

```bash
mkdir -p skills/pet-lookup
```

创建 `skills/pet-lookup/SKILL.md`（下面整段可直接粘贴；接自家 API 时把「宠物」改成你们的资源名即可）：

```markdown
---
name: pet-lookup
description: >
  查询或列出宠物相关信息时使用：须先 list_api 找对工具再 call_api；
  禁止编造 petId；用户未给出可用 ID 时先拉列表或追问，不得猜测后直接调用。
---

# Pet Lookup（练习用）

本 Skill 只约束「怎么查」，业务数据仍来自 MCP（OpenAPI）。

## 何时使用

- 用户要查宠物、列宠物、按状态筛选等（Petstore 或同类资源）

## 步骤

1. 需要调 API 时：先 `list_api` 确认工具与参数，再 `call_api`。
2. 用户只说了名字/模糊描述、没有可用 ID：先列表或追问让用户选定；禁止编造 petId。
3. 工具失败时用人话说明，不要把密钥、完整 Token 回显给用户。

## 禁止项

- 禁止用文档里的示例 ID 顶替真实数据。
- 禁止在本对话里代办登录 / 改密（若遇到 → 走 `account-access`）。
```

要点：

- frontmatter 必填 **`name`**、**`description`**
- **`description` 要具体**：会进「可用 Skills」名片，模型靠它决定要不要 `read_skill`。写太虚（如「处理一切业务」）等于没写
- 正文写清：**何时用 → 步骤 → 红线**；短比长好

---

## 步骤 2：让改动生效

当前没有 Skill 热加载：新建或改 `SKILL.md` 后，**重启 Serve**：

```bash
PYTHONPATH=src uv run python main.py
```

重启后，该 Skill 会出现在「可用 Skills」名片里；相关意图才会去 `read_skill(skill=pet-lookup)`。

本地练手不必提交 Git。若要纳入版本库：根目录 `.gitignore` 默认忽略 `/skills/*`，需像现有公共 Skill 一样加白名单（如 `!/skills/pet-lookup/`）。详见仓库内 [`skills/README.md`](../../skills/README.md)。

---

## 步骤 3：用对话验证

打开演示对话页，发一句能对上 description 的话，例如：

- `帮我查一下商店里有哪些宠物`
- `查一下某个宠物的详情`（故意不给 ID，看会不会先列表或追问）

期望：

1. 过程中出现 **`read_skill`**（参数多为 `pet-lookup`）
2. 随后有 **`list_api` / `call_api`**（若 MCP / Swagger 已配好）
3. **不会**凭空编造一个 petId 就去调详情

若从不读你的 Skill：检查 description 是否和用户说法对得上；确认已重启；确认路径是 `skills/pet-lookup/SKILL.md`，且未被 `skills_exclude` 排除。

仅用 curl 时：

```bash
curl -s http://127.0.0.1:8765/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: skill-demo" \
  -H "X-MCP-Token: demo" \
  -d '{"message":"帮我查一下有哪些宠物，不要瞎猜 ID","stream":false,"wait_profile":"interactive"}'
```

---

## 验收一下

- 存在 `skills/<id>/SKILL.md`，且含 `name` / `description`
- 重启 Serve 后，相关问题会触发 `read_skill`
- 读完 Skill 后仍通过 MCP 调 API（或合理追问），而不是空口编业务结果
- 红线生效（例如禁止编造 ID）

---

## 常见误解

- **Skill 不是可执行插件** — 只是说明书；办事靠企业 API
- **写了不会自动跑脚本** — 暂无脚本执行器；不要在正文里写「必须跑某脚本」
- **改完文件不会立刻生效** — 需要重启 Serve
- **不必一上来写很长** — 入门够用即可；细则放到 [编写 Skill](../usage/write-skill.md)

入门主路径到这里可以告一段落。环境问题再查 [安装与部署](installation.md)；要接更多业务时看 [使用指南](../usage/README.md)。
