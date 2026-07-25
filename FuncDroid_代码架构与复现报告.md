# FuncDroid 代码架构与实验复现完整报告

## 一、项目概述

FuncDroid 是一个面向功能交互流（Inter-Functionality Flow-Oriented, IFO）的移动端 GUI 自动化测试工具（ISSTA 2026）。其核心思想是：**不再将 App 功能视为孤立的线性事件序列，而是建模功能之间的交互关系**，并通过迭代式的 LLM 驱动流程来构建和利用这一模型，从而发现功能相互作用时产生的深度 bug。

整体流程可概括为：
1. 自动探索 App，构建页面转换图（PTG）
2. 从 PTG 中利用 LLM 推断功能流程图（FDG）
3. 分析 FDG 节点间的数据依赖关系
4. 按功能级（Task-level）和跨功能级（App-level）生成并执行测试用例
5. 在探索和测试过程中持续检测 crash 和 functional bug

---

## 二、项目目录结构与模块用途

```
FunDroid/
├── run_funcdroid.sh          # 一键启动脚本（完整流水线）
├── setup_funcdroid.sh         # 环境搭建脚本（Ubuntu 24.04 + ADB + Python venv + .env 配置）
├── test.py                    # LLM API 连通性快速检测（非正式入口）
├── verify_device.py           # 手机连接与 uiautomator2 验证脚本
├── requirements.txt           # Python 依赖
├── funcdroid/                 # ★ 核心代码（注意：导入时使用 hmbot.* 前缀）
│   ├── hmbot.py               # 顶层编排类 HMBot
│   ├── app/                   # App 模型层：解析 APK/HAP 获取元数据
│   │   ├── app.py             #   抽象基类 App
│   │   ├── android_app.py     #   AndroidApp：使用 androguard 解析 APK
│   │   └── harmony_app.py     #   HarmonyApp：鸿蒙应用
│   ├── device/                # 设备抽象层
│   │   ├── device.py          #   Device 类：对 connector + automator 的统一包装
│   │   ├── automator/         #   自动化执行器（实际操控手机）
│   │   │   ├── automator.py   #     抽象基类 Automator
│   │   │   ├── u2.py          #     U2：基于 uiautomator2 的 Android 操控
│   │   │   └── h2.py          #     H2：基于 hmdriver2 的鸿蒙操控
│   │   └── connector/         #   设备连接器（与手机通信）
│   │       ├── connector.py   #     抽象基类 Connector
│   │       ├── adb.py         #     ADB：Android Debug Bridge
│   │       └── hdc.py         #     HDC：Harmony Device Connector
│   ├── model/                 # 核心数据模型
│   │   ├── page.py            #   Page：页面对象（VHT + 截图 + 哈希 + PageInfo）
│   │   ├── vht.py             #   VHT/VHTNode：视图层级树（View Hierarchy Tree）
│   │   ├── event.py           #   事件系统：Click/LongClick/Input/Swipe/Key 等
│   │   └── ptg.py             #   PTG/PTGParser：页面转换图及序列化
│   ├── explorer/              # ★ 核心测试引擎
│   │   ├── explorer.py        #   Explorer 类：PTG/FDG 构建 + 三级测试 + bug 检测
│   │   ├── fdg.py             #   PageNode + FDGNode 数据结构
│   │   ├── llm.py             #   LLM 客户端封装 + Token 统计
│   │   ├── prompt.py          #   全部 LLM 提示词模板（约 15 个）
│   │   ├── action.py          #   底层动作执行函数
│   │   ├── action_parser.py   #   LLM 输出解析（将文本转换为结构化动作）
│   │   ├── utils.py           #   工具函数（权限授予、JSON 清理）
│   │   ├── database.py        #   BugKnowledgeBase：基于 Excel 的 bug 知识库（余弦检索）
│   │   └── knowledge.py       #   KnowledgeBaseRetriever：案例知识库检索
│   └── utils/                 # 通用工具
│       ├── proto.py           #   枚举与 dataclass 定义（操作系统、方向、页面信息等）
│       ├── exception.py       #   自定义异常类
│       ├── cv.py              #   图像处理（Base64 编码、缩放、拼接）
│       ├── utils.py           #   ADB/HDC 设备列表获取
│       └── rfl/               #   反射式分发（根据操作系统选择实现类）
│           ├── system_rfl.py  #     OS → (Connector, Automator) 映射
│           └── strategy_rfl.py#    策略 → 类 映射
└── output/                    # 运行产物输出目录（运行时创建）
```

### 2.1 重要说明：`hmbot` vs `funcdroid` 命名问题

代码中所有 import 均使用 `hmbot.xxx` 前缀（例如 `from hmbot.explorer.llm import ask_llm`），但实际目录名为 `funcdroid/`。这是因为项目原名 `hmbot`，后改名为 `funcdroid`。**setup_funcdroid.sh** 在第 8 步中会自动创建符号链接 `hmbot → funcdroid` 来解决此问题。

---

## 三、各模块详细原理

### 3.1 设备抽象层（`device/`）

#### 3.1.1 Connector（连接器）
- **ADB**：封装 `adb` 命令行调用。核心方法：
  - `page_info()`：通过 `adb shell dumpsys window | grep mCurrentFocus` 获取当前前台 Activity 的包名和 Activity 名，构造 `PageInfo` 对象
  - `shell_grep()`：支持管道 grep，用于复杂系统信息查询
  - `get_uid()` / `get_resources()`：获取应用进程 UID 和资源状态（音频/摄像头）
- **HDC**（鸿蒙）：与 ADB 对称，但使用 `hdc` 命令和 `hidumper` 工具
- 两者通过 **反射式工厂**（`system_rfl`）根据 `OperatingSystem` 自动选择

#### 3.1.2 Automator（执行器）
- **U2**：基于 `uiautomator2` Python SDK
  - `dump_hierarchy()`：调用 `self._driver.dump_hierarchy()` 获取 XML 格式 UI 树，通过 `VHTParser._parse_adb_xml()` 解析为 `VHT` 对象
  - `screenshot()`：直接获取 OpenCV 格式截图（`format='opencv'`）
  - `click(x,y)`：支持 0~1 归一化坐标和像素坐标，自动识别（< 1 视为比例坐标）
  - `input(text)`：使用 `send_keys(text, True)` 清除后输入
- **H2**（鸿蒙）：基于 `hmdriver2`，接口对称

#### 3.1.3 Device 类
对 Connector + Automator 的统一门面。核心方法 `dump_page()`：
```python
def dump_page(self, refresh=False):
    vht = self.dump_hierarchy()     # UI 树
    img = self.screenshot()         # 截屏
    info = self.page_info()         # 当前 Activity 信息
    rsc = self.resources()          # 资源状态
    self.page = Page(vht=vht, img=img, rsc=rsc, info=info)
```
Page 对象有**惰性缓存**：只有 `refresh=True` 时才重新获取，否则复用上一次结果（在探索循环中大幅减少截图/UI 树获取次数）。

### 3.2 数据模型层（`model/`）

#### 3.2.1 Page（页面对象）
一个 Page 包含：
- `vht`：View Hierarchy Tree（UI 树）
- `img`：截图（OpenCV BGR 格式）
- `encoded_img`：截图的 Base64 JPEG 编码（≤800×1400，JPEG quality=85）
- `vht_hash`：**结构哈希**——对 VHT 树自底向上做 MD5，包含每个节点的 type/clickable/bounds 信息
- `feature_set`：所有节点的结构化特征集合（用于 Jaccard 相似度计算）
- `img_hash`：**感知哈希**——使用 `imagehash.phash()`（pHash），用于低差异快速去重（汉明距离 ≤ 2 视为同一页面）
- `info`：PageInfo（bundle/ability/name）

**页面去重算法**（`Explorer._is_page_exist()`）：
1. Activity 名未见过 → 新页面
2. VHT 哈希相同 **且** 感知哈希距离 ≤ 4 → 同一页面
3. 感知哈希距离 ≤ 2 → 同一页面（高度确信）
4. 否则，取 imagehash 最相似的候选页面，发送给 LLM 做视觉比对（仅当相似度在 0.50~0.90 灰色区间时才调用 LLM）→ LLM 判断 "is_same_page"（进行布局结构比较，而不只是内容相似性）

#### 3.2.2 VHT/VHTNode（视图层级树）
- `VHT`：包装根节点的容器，支持 `_compress()` 压缩（合并无互动性的单子节点链）
- `VHTNode`：属性字典 + 子节点列表，支持 `__call__()` 查询（如 `vht(text='Login')`）和 `click()`/`long_click()` 直接操作
- `VHTParser`：两种解析方式——`_parse_adb_xml()`（从 uiautomator2 的 XML）和 `_parse_hdc_json()`（从鸿蒙的 JSON）

#### 3.2.3 FDGNode（功能流图节点）
```python
class FDGNode:
    function_description: str      # LLM 生成的语义描述（如 "Create a new alarm"）
    action_refs: [(page_idx, edge_idx), ...]  # 指向 PTG 中属于该功能的边
    data_in: [str]                 # 消费的抽象数据实体（如 "Note Title"、"Search Keyword"）
    data_out: [str]                # 产生的抽象数据实体（如 "Created Note"、"Filtered List"）
    data_dependencies: [int]       # 此节点依赖的其他 FDG 节点索引
    core_logic: dict | None        # LLM 提取的核心执行逻辑（流程图结构）
    to_test: bool                  # 是否需要测试
```

### 3.3 核心探索引擎（`explorer/`）

#### 3.3.1 LLM 模块（`llm.py`）

有两个 OpenAI-compatible 客户端：
- `client_llm`：通用推理（DeepSeek/GPT-4o），**硬编码在文件中**（需手动修改 base_url 和 api_key）
- `client_uitars`：视觉理解（豆包 Vision/GPT-4o），从环境变量读取（`SPECIALIZED_BASE_URL`、`SPECIALIZED_API_KEY`、`SPECIALIZED_MODEL`）

四个导出函数（均使用 `client_uitars` + OpenAI Responses API + `thinking: disabled`）：
- `ask_llm(content)`：单轮，content 为 `[{type, text/image_url}, ...]`
- `ask_uitars(content)`：同 ask_llm
- `ask_uitars_without_thinking(content)`：同 ask_uitars（显式确认无 thinking）
- `ask_uitars_messages(messages)`：多轮对话，messages 为 `[{role, content: [...]}, ...]`

全局 Token 统计：所有调用累计到 `TOKEN_STATS` dict 和 `TOKEN_LOGS` 列表，最终写入 `LLM-Token-Stats.json`。

**重要**：当前代码中 `client_llm` 被定义但未被使用——所有 LLM 调用都走 `client_uitars`。

#### 3.3.2 提示词模块（`prompt.py` + `explorer.py` 内联）

全部 LLM 提示词共约 20 个，分布在 `prompt.py`（16 个全局定义）和 `explorer.py`（5 个内联定义）中。以下按使用阶段分类列出完整原文。

> **命名约定**：`prompt.py` 中的变量使用 snake_case（如 `get_widgets_from_page_prompt`），`explorer.py` 内联定义的局部变量使用 UPPER_SNAKE_CASE（如 `FDG_EDGE_CLASSIFY_PROMPT`）。`test_function_prompt` 和 `FDG_function_description_prompt` 在两处各有一份定义（内联版本覆盖导入版本）。

---

##### A. Phase 1: PTG 探索阶段

**a) `initial_page_prompt`** — 首页控件识别（`prompt.py:63`）

> 与 `get_widgets_from_page_prompt` 的区别：无需前后对比，且对 Bottom Tab 栏有特殊规则——必须全部枚举而非去重。

```text
You are a professional Mobile GUI Analysis Assistant. You will receive a screenshot of a mobile app's current page.

### Core Task
Analyze the screenshot to accurately identify all interactive widgets, adhering to the specified criteria.

### 1. Widget Recognition Standards
- Define "interactive widgets" as elements supporting user actions (e.g., click, input, state toggle).
- For batch identical-function widgets (e.g., repetitive cards in a list/grid), select **only one representative** (avoid redundant entries),
  **except for Bottom Tab bars**.
- Ensure no omission of unique interactive elements; prioritize functional distinctiveness over visual duplication.

### 2. Bottom Tab Bar (Special Rule — MUST FOLLOW)
- **All Bottom Tab bar items MUST be identified individually**, even if they share similar structure or appearance.
- Do NOT deduplicate Bottom Tab items. Each tab (e.g., Home, Search, Favorite, Settings) must be listed as a separate widget.
- Treat Bottom Tab items as navigation controls (`is_leaf = false`).

### 3. Field Definitions (Precise Guidelines)
- is_leaf:
  - `true`: Widgets that toggle states (Switch, Checkbox) or select options **without triggering page navigation/redirection**.
  - `false`: Widgets that initiate page navigation, confirm actions (Login, Search, Submit), or **open new layers/pages**
    (including Bottom Tab switches, modals, and tab changes).
- content:
  - Input Fields: Generate a **contextually relevant, realistic sample value** aligned with the field's label/hint (avoid generic placeholders).
  - Clickable Elements (buttons, links, toggles): Return an empty string "".

### Important Notes
- Bottom Tab bar widgets are an exception to the representative-widget rule and must be **fully enumerated**.
- Representative Widget per Category applies ONLY to non-tab repetitive items (e.g., list cards, grid items).

### Output Format (Strict Compliance)
Return **exactly one JSON object** (no markdown code fences, comments, or extra text).
{
  "function_description": "Concise summary of the page's core function (≤20 words)",
  "widgets": [
    {
      "description": "Clear, functional description of the widget (≤20 words)",
      "action": "click" or "input",
      "content": "Sample value if 'input'; empty string '' if 'click'",
      "position": [x, y], // Center coordinates (normalized 0–1000)
      "is_leaf": true/false,
      "postcondition": "Concise prediction of immediate post-interaction behavior (≤30 words)"
    }
  ]
}
```

**b) `get_widgets_from_page_prompt`** — 从前后页面对比中提取新增交互控件（`prompt.py:1`）

```text
You are a professional Mobile GUI Analysis Assistant. You will receive:
1. A screenshot before action.
2. A screenshot after action (current page).
3. The user action performed.

### Core Task
Analyze the screenshots to accurately identify all interactive widgets on the current page, adhering to the specified criteria.

### 1. Widget Recognition Standards
#### 1.1 Definition of Interactive Widgets
- Interactive widgets refer to elements supporting user operations, including but not limited to: clickable buttons, input fields, state-toggle widgets (Switch/Checkbox), dropdown menu options, and operation buttons in popups.

#### 1.2 Core Scope (Based on Screenshot Comparison)
- Compare the "screenshot before action" and "current page screenshot" strictly; **only identify interactive widgets that are newly added or newly visible on the current page**.
- Fully ignore interactive widgets that already existed and remained unchanged in the "screenshot before action".

#### 1.3 Deduplication & Batch Widget Handling Rules
- For batch identical-function widgets (e.g., homogeneous cards in a list, multiple identical buttons) on the current page: select **only one representative** to avoid redundant entries.
- For functionally differentiated widgets (e.g., different options in a dropdown menu, buttons with distinct labels): retain all without deduplication.
- For long homogeneous data lists (e.g., list rows with identical structure): extract **only one representative item** (do not identify all entries).

#### 1.4 Exclusion Rules
- Ignore system-level UI elements (e.g., system Back/Home buttons) unless the current page has no other interactive widgets.
- Ignore persistent static elements (e.g., top navigation bar, bottom tab bar) that show no visual changes compared to the "screenshot before action" (do not re-identify them).

### 2. Field Definitions (Precise Guidelines)
- is_leaf:
  - `true`: Widgets that toggle states or select options **without triggering page navigation/redirection**.
  - `true`: Log out buttons or exit actions that close the app without navigating to another page.
  - `false`: Widgets that initiate page navigation, confirm actions, or **open new layers/pages**.
- content: Generate contextually relevant, realistic sample values for input fields; empty string for clickables.
- postcondition: Concise prediction of immediate behavior after interaction (≤30 words).

### Output Format (Strict Compliance)
Return **exactly one JSON object** (no markdown code fences, comments, or extra text).
{
  "function_description": "Concise summary of the page's core function (≤20 words)",
  "widgets": [
    {
      "description": "Clear, functional description of the widget (≤20 words)",
      "action": "click" or "input",
      "content": "Sample value if 'input'; empty string '' if 'click'",
      "position": [x, y], // Normalized 0-1000
      "is_leaf": true/false,
      "postcondition": "Concise prediction (≤30 words)"
    }
  ]
}
```

**c) `get_position_prompt`** — Widget 坐标重定位（`prompt.py:268`）

> 每次点击前调用，让 LLM 在当前截图上重新定位 widget。避免因页面滚动/布局变化导致坐标失效。最多重试 3 次。

```text
You are a mobile app GUI analysis expert.

You will receive:
1) A screenshot of the current app page.
2) A text description of a target widget on this page.

Your task:
Determine the precise center coordinates of the target widget on the screenshot.

Rules:
- If the target widget is found, return its center coordinates as [x, y], where x and y are integers representing pixel positions.
- If the target widget cannot be found or cannot be confidently identified, return [0, 0].

Output format:
Return ONLY a JSON object with NO extra text. The JSON object MUST contain the key "position".
Example when found: {"position": [123, 456]}
Example when not found: {"position": [0, 0]}
```

**d) `page_exist_prompt`** — 页面去重 LLM 视觉比对（`prompt.py:662`）

> 当 imagehash 落在 0.50~0.90 灰色区间时调用。判断标准：**结构相同即同一页面**，忽略动态内容差异。

```text
You are a professional mobile app GUI comparison expert. You will be provided with:
1. A new screenshot (current page to verify).
2. The most similar known candidate page (from historical screenshot library).

### Core Task
Determine whether the new screenshot represents the **same page** as the candidate page, following the strict judgment rule:
**Pages with identical structural layout (regardless of content differences) are considered the same page.**

### Judgment Criteria
1. **Structural Identity (Primary Criterion)**:
   - Evaluate overall page layout, main functional sections, key widget placement, and navigation structure.
   - If the core structural framework is consistent, the pages are deemed the same, regardless of content changes.

2. **Ignorable Differences (Do NOT affect judgment)**:
   - Dynamic content updates (e.g., text, images, list items, numerical values).
   - Minor temporary elements (e.g., pop-up tips, loading spinners, notification badges).
   - Cosmetic changes (e.g., slight color adjustments, font size variations) that do not alter layout structure.

3. **Differences That Change Page Identity**:
   - Alteration of main section layout (e.g., content area replaced, header/footer structure modified).
   - Addition/removal of core functional sections (e.g., new sidebar, missing bottom navigation bar).
   - Fundamental shift in key widget placement (e.g., search bar moved from top to bottom).

### Output Requirements
Return ONLY a single JSON object with no explanations, comments, or extra text:
{"is_same_page": true or false}
```

---

##### B. Phase 2: FDG 构建阶段

**e) `FDG_EDGE_CLASSIFY_PROMPT`** — PTG 边分类：是否新功能点（`explorer.py:141` 内联）

> BFS 遍历 PTG 时，用此 prompt 判断每条边是"同一功能内步骤"还是"新功能起点"。同时提取 data_in/data_out。

```text
You are identifying functional points and their boundaries in a mobile app.

Task:
Given the DESCRIPTION of the CURRENT functional point and the UI screenshots BEFORE and AFTER an action, decide whether this action starts a NEW functional point, or it is still part of the CURRENT functional point.

What is a "functional point"?
A functional point is a self-contained user goal that the user perceives as ONE function/goal. A functional point can be completed by a single action (one-edge function) or multiple actions (a workflow).

Core principle (do NOT be too broad):
- Do NOT merge many unrelated things into one big functional point (especially on Settings pages).
- A functional point must have a clear and specific purpose/effect, not a vague umbrella like "Settings".

Boundary rules:

1) Navigation / feature entry
- If the action clicks a feature item on a navigation list / home menu / drawer / tab list and enters that feature, then that clicked feature item should be treated as the start of a NEW functional point.
  Example: "Notes" / "Calendar" / "Search" / "Settings" items in a navigation list → each item is a new functional point.

2) Goal completion within the same function (one workflow)
- If the action is a step to complete the same user goal within ONE feature page/workflow, it is NOT a new functional point.
  Example 1: On a "Create Note" page, typing title/body, adding tags, and tapping "Save" are all part of "Create Note".
  Example 2: When saving/exporting a file, the app may navigate to a "File picker" page. Selecting a folder and confirming are still part of the SAME functional point (Save/Export File).

3) Settings page rule (MUST be fine-grained)
- On a Settings page, each distinct setting item (including toggles/switches) is its own functional point.
  Example: "Theme", "Font size", "Sync", "Notifications" → each setting item is a NEW functional point.
- A setting item can be a one-edge functional point even if the UI does NOT navigate to a new page.
- The options/configurations within the SAME setting item are NOT new functional points.

Also extract abstract data:
- "data_in": abstract data entities that this action uses/loads/edits/operates.
- "data_out": abstract data entities that this action produces or updates.
- Only include ABSTRACT entities (not UI widget names, not button text, not coordinates).
- Use short noun phrases; de-duplicate; do not invent data not implied by the UI.

Output (STRICT JSON ONLY):
{
  "new_functional_point": true/false,
  "data_in": ["<abstract entity>", ...],
  "data_out": ["<abstract entity>", ...]
}
Do NOT output any extra text, explanation, comments, or code fences outside the JSON.
```

**f) `FDG_FUNCTION_DESCRIPTION_PROMPT`** — FDG 节点功能描述（`explorer.py:202` 内联，覆盖 prompt.py 同名变量）

```text
App: {app_name}

You are given a navigation path description to reach the current page. Summarize the functionality of the current page as a concise function description (one sentence).

Path:
{path_description}

Return only plain text.
```

**g) `FDG_CORE_LOGIC_PROMPT`** — FDG 节点核心逻辑提取（`explorer.py:214` 内联）

> 将属于同一功能的 action_refs 列表 + 关键页面截图发给 LLM，提取流程图式核心逻辑。

```text
You are extracting the CORE EXECUTION LOGIC of a mobile app functional point.

App: {app_name}

Functional point description (high-level):
{function_description}

Below is the set of actions that belong to this functional point.
Each action is a PTG edge reference, and contains:
- action_ref: [page_idx, edge_idx], src_page_idx, dst_page_idx (may be null)
- action (e.g., click / input), description / content / position / is_leaf

Your task:
1) Build a FLOWCHART-LIKE structure that captures the core execution logic of this functional point:
   - ordered steps (sequence)
   - branch points (if-else / loop) when the flow can diverge or repeat
2) Every step MUST correspond to EXACTLY ONE provided action_ref (no invented steps).
3) The final output must be STRICT JSON that follows the schema below.

CRITICAL CONSTRAINTS (MUST FOLLOW):
A) No hallucination:
   - You MUST NOT invent steps/actions that are not backed by the given actions list.
   - Every "steps[i].action_ref" MUST appear in the given actions list.
B) Reference integrity:
   - All step ids referenced in "flow_edges" and "branch_points" MUST exist in "steps".
   - "flow_edges[].from/to" must be valid step ids.
   - "branch_points[].at_step" must be a valid step id.
   - Every "branches[].next_step" must be a valid step id.
C) Branch conditions:
   - If you describe conditions (in summaries), they MUST be UI-observable
     (e.g., "toggle is off", "input is empty", "dialog appears"),
     NOT program variables, NOT internal states, NOT coordinates.
D) Output field "logic" definition:
   - "logic" MUST be a NATURAL-LANGUAGE description of the CORE EXECUTION LOGIC (2–6 sentences).
   - It must summarize the main flow in order, and explicitly mention major decision/loop points if any.
   - Do NOT include testing oracles, assertions, mutations, or implementation details.
   - Do NOT mention coordinates, view ids, or program variables.

Output STRICT JSON (NO extra text, NO markdown):
{
  "entry_page": <int|null>,
  "logic": "<natural-language description of the core execution logic, 2-6 sentences>",
  "steps": [
    {
      "id": "S1",
      "action_ref": [page_idx, edge_idx],
      "src_page_idx": <int>,
      "dst_page_idx": <int|null>,
      "action": "<string>",
      "summary": "<what this step does>"
    }
  ],
  "flow_edges": [
    {"from": "S1", "to": "S2"}
  ],
  "branch_points": [
    {
      "at_step": "S2",
      "type": "if-else" or "loop",
      "branches": [
        {"next_step": "S3"},
        {"next_step": "S4"}
      ]
    }
  ]
}
```

**h) `page_to_widget_prompt`** — Widget 级功能点判断（`prompt.py:483`）

```text
You are a mobile app GUI functional analysis expert.

You will be given:
1. A screenshot of the current page.
2. The functional description of a control on this page.

Your task is to determine if this control represents a new functional point and analyze its specific data usage.

### Part 1: Functional Point Determination
- Return `true` if the control **leads to a new functional module or distinct feature page**.
- Return `false` if the control **changes a state, option, or setting inside an existing feature page**.
- **Group Rule**: If multiple controls belong to the same selection group, they are NOT separate functional points.

### Part 2: Concrete Data Flow Analysis (STRICT)
Identify the **SPECIFIC** data entities this control reads or modifies.
**DO NOT use generic terms.** Be specific about *what* is being handled.
- **data_in**: What specific data does this widget take in? (e.g., "Credit Card Number", "City Name")
- **data_out**: What specific data does this widget produce or change? (e.g., "Saved Contact", "Bluetooth State: Off")
- If it's a simple navigation button, data lists should be `[]`.

### Input
Control functional description: "{function_description}"

### Output format
Return in JSON:
{
  "new_functional_point": true or false,
  "data_in": ["string", ...],
  "data_out": ["string", ...]
}
Do not include explanations or any extra text.
```

---

##### C. Phase 3: 数据依赖推断

**i) `data_flow_prompt`** — 推断 FDG 节点间数据依赖（高召回）（`prompt.py:596`）

> 基于 data_in/data_out + 功能描述进行匹配。高召回策略：语义等价的实体视为匹配。

```text
You are an expert in mobile app functional dependency analysis.

You are given several functional nodes. Each node has:
- index: integer
- description: what this function does
- data_in: data it uses or requires
- data_out: data it produces or updates

Your task:
Infer **data dependencies for each node**.

Definition: data_dependencies (j depends on i)
- "i → j" means: Node j uses/reads/edits/displays data that could be produced/updated by Node i.
- You must output **for each consumer node j**, which producer nodes i it depends on.

Core rule (must use):
- If j.data_in contains an abstract data entity that is the same as (or semantically equivalent to) an entity in i.data_out, then include i in j.data_dependencies.

Relaxed rules (high recall):
- Treat semantically similar / renamed data as the same entity (e.g., "expense record" vs "expense list").
- If j logically continues, views, edits, deletes, filters, exports, shares, or shows statistics/history/summary for data created or updated by i, then include i → j.
- Ignore pure navigation or UI-only actions with no real data usage.

Output format — Return ONLY one valid JSON object:
{
  "data_dependencies": {
    "1": [0],
    "2": [0, 3]
  }
}
Keys MUST be strings of the consumer indices. Values are lists of integers (producer node indices).
Do NOT include a node j if it has no dependencies. Do NOT include self-dependency.
Prefer INCLUDING a dependency when it is reasonably likely.
```

**j) `data_flow_prompt_without_data`** — 推断 FDG 节点间数据依赖（高精度）（`prompt.py:697`）

> 仅从功能描述推断，无 data_in/out。高精度策略：宁可少不可错。仅当强证据时才添加依赖。

```text
You are an expert in mobile app functional dependency analysis.

You are given several functional nodes. Each node has:
- index: integer
- description: what this function does

Your task:
Infer **data dependencies for each node** based ONLY on the descriptions.

STRICT extraction policy (precision-first):
- Extract as FEW dependencies as possible.
- Add a dependency ONLY when the relationship is STRONGLY supported by the descriptions (high confidence).
- If the relationship is ambiguous or only weakly related, DO NOT include it.

Strong-evidence rules (must satisfy at least ONE):
1) Same explicit entity — i and j clearly mention the same concrete entity type, and i creates/updates/deletes it while j views/edits/shares/exports/searches/filters it.
2) Explicit create→consume pipeline — i clearly produces an output that j clearly consumes.
3) Specific setting effect — i changes a clearly named setting/toggle, and j clearly indicates behavior/UI that depends on that exact setting.

Representative-only rule for similar dependencies (IMPORTANT: dedup):
- If multiple candidate dependencies are essentially the SAME kind of relationship, output ONLY ONE representative dependency and ignore the rest.
- Goal: Do NOT generate too many dependencies. Prefer fewer, high-confidence, representative dependencies over exhaustive coverage.

Output format — Return ONLY one valid JSON object:
{
  "data_dependencies": {
    "1": [0],
    "2": [0, 3]
  }
}
```

**k) `filter_fdg_prompt`** — FDG 节点筛选（`prompt.py:556`）

> 过滤掉纯导航/低价值节点，仅保留有具体用户功能的节点用于测试。

```text
You are a mobile app testing expert.

You are given a list of FDG nodes (functional points). Each node has:
- an integer index
- a short text description of what this node does in the app

Your goal is to select which nodes are WORTH TESTING as independent test targets.

## Selection Rules
1. KEEP a node if its description shows a **concrete, user-visible functionality** (create / add / edit / delete / submit / save / confirm / search / filter / sort / share / export / import / login / register / sync, etc.).
2. REMOVE a node if its description is **only navigation or very low-value** (pure navigation: open page, go to details, back, close, open tab, open menu, generic containers).
3. If a node description is **too vague or unclear**, treat it as low-value navigation and REMOVE it.

Output format:
{"to_test_nodes": [0, 3, 5]}
Do not add explanations, comments, or any other fields.
```

---

##### D. Phase 4: 测试阶段

**l) `test_function_prompt`** — 功能测试 Agent 指令（`prompt.py:115`）

> 控制测试 Agent 的行为空间和输出格式。支持 `click`/`input`/`long_click`/`press_back`/`finished` 五种动作。

```text
You are a GUI testing agent. Your goal is to test a specific function on the current app screen according to the user's instruction.

## Action Space
You can only use these actions:
- `click(point='<point>x y</point>')`: Click a coordinate.
- `long_click(point='<point>x y</point>')`: Long click a coordinate.
- `input(content='...')`: Input text (use "\n" to confirm or submit).
- `press_back()`: Press the back button.
- `finished(content='xxx')`: Mark the task as fully complete.

## Important Notes
If an action causes **any abnormal situation**, **immediately stop** and output a `finished` action with a short reason.
Abnormal situations include: App crash or unexpected close, Wrong or unexpected page jump, Page freeze or no response to interaction, UI layout corruption or broken display, Any unexpected or undefined behavior.
Example: `Action: finished(content='App crashed after clicking the button.')`

## Output Format
Return exactly in the following format:
Thought: [Brief reasoning about what to do next]
Action: [A single valid action from the Action Space]
Description: [A short natural-language description of what this action does]

## Function to Test
{instruction}
```

**m) `TASK_MUTATION_PROMPT`** — Task 级变异测试用例生成（`explorer.py:1247` 内联）

> 对每个 FDG 节点的 core_logic，生成 2~3 个变异路径（分支变异、顺序变异、重复/省略、边界输入）。

```text
You are generating MUTATION test cases for a mobile app functional point.

You will be given:
- Functional point description
- Core logic summary (natural language)
- widget_descriptions: a list of UI widgets/actions descriptions available within this functional point (strings)

HARD CONSTRAINT (MUST FOLLOW):
- You can ONLY interact with widgets that appear in widget_descriptions.
- When you reference a widget, you MUST copy its description EXACTLY and wrap it using <....>.
  Example: Tap <Add note>, Long-press <Item options>, Input "abc" into <Title field>.
- Do NOT mention any other buttons/menus/settings not in widget_descriptions.
- If you cannot generate valid mutations using only these widgets, return an empty list.

Mutation goals (high-risk):
1) Branch mutation: choose alternative widgets/options among the list.
2) Order mutation: swap two independent steps if plausible.
3) Repeat/omit: repeat an operation or omit a step (e.g., try saving without input).
4) Boundary input: empty / very long / special chars ONLY if input is plausible.

Output STRICT JSON ONLY:
{
  "variant_paths": [
    "natural language task 1",
    "natural language task 2"
  ]
}
The length of variant_paths must be less than or equal to 3.
```

**n) `APP_LEVEL_PLAN_PROMPT`** — 跨功能测试用例规划（`explorer.py:1442` 内联）

> 对每对 (Producer, Consumer) 依赖，生成跨功能测试用例。

```text
You are an expert in cross-functional testing for mobile apps.

You are given two functional points with a data dependency: Producer -> Consumer.
Producer produces/updates some abstract data_out that may be consumed by Consumer via data_in.

Your task:
Generate a LIST of cross-functional test cases to validate the dependency across these two functions.

Requirements:
- Each test case MUST execute the Producer first to create/update the required data, then execute the Consumer to use/view/edit that data.
- Provide clear natural-language task instructions that a UI testing agent can follow.
- Focus on verifying the dependency: the Consumer should reflect/use the data produced by the Producer.
- Do NOT invent steps that are not supported by the provided core_logic steps; you may rephrase core_logic into tasks.
- Output no more than 2 test cases.

Output STRICT JSON ONLY (and nothing else):
[
  {
    "producer_task": "<natural-language task for producer core logic>",
    "consumer_task": "<natural-language task for consumer core logic>"
  }
]
```

**o) `get_widget_test_prompt`** — Widget 级单控件测试（`prompt.py:219`）

```text
You are a mobile app GUI testing assistant.

You will receive:
1) A screenshot of the current page.
2) A text description of ONE target widget to test.

Your task:
Based on the screenshot and the target widget, design simple test cases.
Each test case MUST contain exactly:
- ONE action (click or input).
- ONE context (only used when action = "input", otherwise MUST be an empty string "").
- ONE postcondition (the expected result after this operation).

Rules for action:
- The "action" field must be exactly one of: "click", "input".
- Across ALL test cases: "click" can appear AT MOST ONCE. "input" can appear AT MOST ONCE.
- If action = "input", then "context" MUST be non-empty.
- If action = "click", then "context" MUST be exactly "".

Output format — Return ONLY a JSON object with NO extra text:
{
  "tests": [
    {"action": "click", "context": "", "postcondition": "The details dialog is shown."},
    {"action": "input", "context": "typed empty title", "postcondition": "An error message is shown."}
  ]
}
```

**p) Widget 级测试流生成 prompt** — Widget test flow（`explorer.py:1150` 内联 f-string）

```text
You are a mobile app GUI testing assistant.

You are given:
1) A screenshot of a page.
2) The natural-language description of ONE interactive widget on this page.

Your task:
1. Design a short TEST FLOW (string description) that exercises ONLY this widget.
2. Predict the EXPECTED RESULT (string description) of this flow.

Rules:
- Focus ONLY on this widget.
- The flow should be a sequence of actions described in natural language (e.g., "1. Click X. 2. Input Y.").
- Use realistic example text if input is needed.
- Keep it concise (3-5 steps max).

Return ONLY one JSON object with exactly two keys: "steps" and "expected_result".
Format example:
{
    "steps": "1. Tap the search bar. 2. Input 'test item'. 3. Tap the search icon.",
    "expected_result": "The search results page is displayed showing items related to 'test item'."
}

Widget description: "{widget_desc}"
```

**q) `task_planning_prompt`** — 测试路径规划（`prompt.py:522`）

> 生成 1 个主路径 + 2~3 个变体路径（边界/异常测试）。

```text
You are a Mobile App QA Automation Expert.

Your Task:
Based on the function description and the provided UI context, generate test paths for: "{task_description}".

You must generate two types of paths:
1. **One Main Path (Happy Path)**: The standard, successful sequence of actions to complete the task perfectly.
2. **2-3 Variant Paths (Edge Cases/Negative Tests)**:
   - Deviate from the main path to test robustness.
   - Examples: Skipping optional steps, omitting required inputs, attempting actions in wrong order, or submitting empty forms.

### Output Format
Return a single JSON object:
{
  "main_path": "String describing the steps. Format: 1. [Action]... 2. [Action]...",
  "variant_paths": [
    "String for Variant 1. Format: 1. [Action]...",
    "String for Variant 2..."
  ]
}

### Example Strategy
If the task is "Login":
- "main_path": "1. Input username. 2. Input password. 3. Tap Login."
- "variant_paths": ["1. Input username. 2. Tap Login (Skip password).", "1. Tap Login (Empty fields)."]

Do NOT include markdown code blocks (```json). Return raw JSON only.
```

---

##### E. Phase 5: Bug 检测

**r) `bug_detection_prompt`** — 实时 Bug 检测（`prompt.py:323`）

> 在探索过程中，每执行一个动作后调用。对比前后截图 + 动作描述，判断是否出现 crash 或 functional bug。

```text
You are a mobile app testing assistant.

You will receive:
- Screenshot before a user action.
- Screenshot after the user action.
- A description of the user action.

Your task: Decide whether there is a bug.

You should focus on two categories:
1) Crash bugs
2) Functional bugs

### 1. Crash Bugs
Crash bugs ONLY include:
- Explicit app crash dialogs (e.g., "App has stopped", "App keeps stopping").
- The app process exits after the action and the system home screen (launcher/desktop) is shown.

### 2. Functional Bugs
A functional bug means: the app runs, but the actual result after this action clearly does NOT match the expected state.

Typical functional bugs include:
- An operation that should update something, but no update happens at all.
- Data is updated incorrectly (wrong value displayed, obviously wrong calculation result, incorrect total or count).
- Data is missing or duplicated (newly added item does not appear in the list, same item appears twice).

IMPORTANT:
- Do NOT treat minor visual or layout differences as functional bugs.
- Do NOT treat navigation to an unexpected page or screen as a functional bug by itself.
- Do NOT treat informational messages, reminders, warnings, tips, guidance prompts, or toast messages as bugs.
- Do NOT treat blank or empty pages resulting from incomplete loading as functional bugs.
- Only consider an issue a functional bug if the application's functional behavior or data state clearly violates the expected outcome.

Return ONLY one JSON object:
{
  "has_bug": true or false,
  "bug_type": "crash" | "functional" | "none",
  "bug_description": "Short description (<=50 words)"
}
```

**s) `path_bug_detection_prompt`** — 路径级 Bug 检测（`prompt.py:156`）

> 功能测试完成后调用。拥有完整执行序列上下文，可检测累积 bug。

```text
You are a Mobile App QA Expert.
You are given a sequential execution log (Path Record) of an automated test.
Each step contains a screenshot and a description of the state/action.

Your task: Decide whether there is a bug.

You should focus on two categories:
1) Crash bugs — App crash dialogs, system error dialogs, completely blank/frozen screen.
2) Functional bugs — The functional outcome clearly does NOT match the expected behavior:
   - Operation should update something, but no update happens.
   - Data is updated incorrectly.
   - Data is missing or duplicated.
   - A button that should be available is disabled or unresponsive.
   - A confirmation message is inconsistent with the performed action.

IMPORTANT:
- Do NOT treat minor visual/layout changes as functional bugs.
- Do NOT treat "navigated to an unexpected page" as a functional bug by itself.
- Only consider navigation-related issues as a bug if they lead to a crash or completely broken state.
- If you are not sure, be conservative and set has_bug = false.

Return ONLY one JSON object:
{
  "has_bug": true or false,
  "bug_type": "crash" | "functional" | "none",
  "bug_description": "Short description (<=50 words)"
}
```

**t) `bug_recheck_prompt`** — 知识库辅助 Bug 二次确认（`prompt.py:370`）

> 更保守的判别策略：若与已知非 Bug 案例相似则判定为非 Bug。与知识库检索配合使用（当前代码中已注释）。

```text
You are a mobile app testing assistant.

You will receive:
- Screenshots before and after a user action for the CURRENT case.
- A description of the user action.
- Several NON-BUG reference examples from a knowledge base.
  These reference examples represent NORMAL and CORRECT app behaviors and MUST NOT be considered defects.

Your task:
Re-evaluate whether the CURRENT case is truly a bug, by comparing it with the NON-BUG reference examples.

You should be MORE conservative than the initial detection.

Decision principles:
- If the CURRENT case is semantically or visually similar to any NON-BUG reference example, then it is NOT a bug.
- Only report a bug if the CURRENT case clearly violates the expected state AND is clearly different from all NON-BUG reference examples.

Typical functional bugs include:
- An operation that should update something, but no update happens at all.
- Data is updated incorrectly (wrong value, wrong calculation, incorrect count).
- Data is missing or duplicated unexpectedly.

IMPORTANT:
- Do NOT treat minor visual or layout differences as functional bugs.
- Do NOT treat navigation to an unexpected page or screen as a functional bug by itself.
- Do NOT treat informational messages, reminders, warnings, tips, or confirmation dialogs as bugs.
- Do NOT treat blank or empty pages caused by incomplete loading as functional bugs.

Final decision rule: If there is ANY reasonable doubt, choose NOT A BUG.

Return ONLY one JSON object:
{
  "has_bug": true or false,
  "bug_description": "Short description (<=50 words)"
}
```

---

##### F. 辅助/未使用 Prompts

**u) `event_llm_prompt`** — 通用 GUI Agent（`prompt.py:298`）

> 旧版 GUI agent prompt，仅支持 click/long_click/input 三种动作。当前代码未使用。

```text
You are a GUI agent designed to follow instructions and interact with a user interface.

## Action Space
Your **only** available actions are:
- `click(point='<point>x y</point>')`: Clicks a specific coordinate on the screen.
- `long_click(point='<point>x y</point>')`: Performs a long click at the specified coordinate.
- `input(point='<point>x y</point>', content='...')`: Inputs the given content. To submit after typing, append "\n".

## Output Format
You **MUST** return your response in the following format:
Action: [A single action from the Action Space]

## User Instruction
{instruction}
```

**v) `page_to_page_prompt`**（`prompt.py:437`）— 边分类备选

> 与 `FDG_EDGE_CLASSIFY_PROMPT`（explorer.py 内联版）功能相同，但 prompt.py 版本更简洁。实际运行使用的是 explorer.py 内联版。

```text
You are a mobile app interaction expert.
Given a user action description and two screenshots (before and after the action), analyze the interaction to determine functional changes and specific data flow.

### Part 1: New Functional Point Detection
A "New Functional Point" represents a distinct change in the functional context or the emergence of a new interactive layer.

**Return `true` (New Functional Point) if:**
1. Page Navigation: Full-screen transition.
2. Tab/Module Switching: Switching major modules.
3. Modal/Dialogs: Popup/Alert requiring attention.
4. Bottom Sheets/Action Panels: Panels offering distinct actions.
5. Side Drawers: Navigation drawer slides in.

**Return `false` (Same Functional Point) if:**
1. Inline UI Changes: Expanding accordions, "read more".
2. Simple Inputs: Typing, toggling switches, checkboxes.
3. Dropdowns/Menus: Simple selection within a form.
4. Transient UI: Toasts, loading spinners.
5. Scroll/Swipe: Moving viewport without structural change.

### Part 2: Concrete Data Flow Analysis (STRICT)
Identify the **SPECIFIC** data entities consumed or produced.
**DO NOT use vague terms** like "User Data", "Settings", "Info", "Input".
- **data_in**: Specific entities used/required (e.g., "Note Title", "Search Keyword", "Login Credentials")
- **data_out**: Specific entities created/modified/loaded (e.g., "Created Note Entry", "Filtered Product List", "WiFi State: On")
- **Empty Rule**: If the action is purely navigational with no data logic, return [].

### Output format
Return exactly one JSON object:
{
  "new_functional_point": true or false,
  "data_in": ["string", ...],
  "data_out": ["string", ...]
}
Do not include explanations or any extra text.
```

**w) `FDG_function_description_prompt`**（`prompt.py:414`）— FDG 节点描述备选

> prompt.py 版本，与 explorer.py 内联版功能一致但变量命名不同（snake_case vs UPPER）。运行使用的是内联版。

```text
You are a mobile app functional analysis expert. The app you are analyzing is {app_name}.

You will be given:
1. The full navigation path that led to the current page (including pages and user actions).
2. A screenshot of the current page.

Your task:
Summarize the function of the current page in the context of the entire navigation path.

Rules:
- Do NOT describe individual buttons or UI components.
- Do NOT repeat the navigation path.
- Do NOT include explanations or reasoning.

Navigation Path: {path_description}

Output Format:
Return only a concise, high-level functional description. No explanations, reasoning, or JSON structure.
```

---

##### 汇总表

| # | Prompt 名称 | 位置 | 阶段 | 用途 |
|---|---|---|---|---|
| a | `initial_page_prompt` | prompt.py:63 | PTG 探索 | 首页控件识别（Bottom Tab 全枚举） |
| b | `get_widgets_from_page_prompt` | prompt.py:1 | PTG 探索 | 前后页面对比提取新增交互控件 |
| c | `get_position_prompt` | prompt.py:268 | PTG 探索 | Widget 坐标重定位 |
| d | `page_exist_prompt` | prompt.py:662 | PTG 探索 | 页面去重 LLM 视觉比对 |
| e | `FDG_EDGE_CLASSIFY_PROMPT` | explorer.py:141 | FDG 构建 | PTG 边分类：新功能点判断 + data_in/out |
| f | `FDG_FUNCTION_DESCRIPTION_PROMPT` | explorer.py:202 | FDG 构建 | FDG 节点功能描述 |
| g | `FDG_CORE_LOGIC_PROMPT` | explorer.py:214 | FDG 构建 | FDG 节点核心逻辑提取（流程图结构） |
| h | `page_to_widget_prompt` | prompt.py:483 | FDG 构建 | Widget 级功能点判断 |
| i | `data_flow_prompt` | prompt.py:596 | 数据依赖 | 推断 FDG 节点间依赖（高召回） |
| j | `data_flow_prompt_without_data` | prompt.py:697 | 数据依赖 | 推断依赖（高精度，无 data_in/out） |
| k | `filter_fdg_prompt` | prompt.py:556 | 数据依赖 | FDG 节点筛选（过滤纯导航） |
| l | `test_function_prompt` | prompt.py:115 | 测试 | 功能测试 Agent 指令 |
| m | `TASK_MUTATION_PROMPT` | explorer.py:1247 | 测试 | Task 级变异测试用例生成 |
| n | `APP_LEVEL_PLAN_PROMPT` | explorer.py:1442 | 测试 | 跨功能测试用例规划 |
| o | `get_widget_test_prompt` | prompt.py:219 | 测试 | Widget 级单控件测试 |
| p | Widget test flow prompt | explorer.py:1150 | 测试 | Widget 测试流生成（内联 f-string） |
| q | `task_planning_prompt` | prompt.py:522 | 测试 | 测试路径规划（主路径 + 变体） |
| r | `bug_detection_prompt` | prompt.py:323 | Bug 检测 | 实时 Bug 检测（探索中） |
| s | `path_bug_detection_prompt` | prompt.py:156 | Bug 检测 | 路径级 Bug 检测（测试后） |
| t | `bug_recheck_prompt` | prompt.py:370 | Bug 检测 | 知识库辅助 Bug 二次确认 |
| u | `event_llm_prompt` | prompt.py:298 | 未使用 | 旧版 GUI Agent prompt |
| v | `page_to_page_prompt` | prompt.py:437 | 未使用 | 边分类备选（被内联版覆盖） |
| w | `FDG_function_description_prompt` | prompt.py:414 | 未使用 | FDG 描述备选（被内联版覆盖） |

#### 3.3.3 Explorer 类（`explorer.py`）- 核心引擎

这是整个系统的核心，约 2500 行。以下是其完整工作流程：

##### Phase 0: 初始化
```python
explorer = Explorer(device=device, app_name=app.app_name, app=app)
explorer.time_limit_seconds = 3600  # 默认 1 小时
```
初始化时启动**后台 bug 检测线程**（`bug_detector_thread`），从 `bug_queue` 中取任务执行。

##### Phase 1: PTG 探索（`_explore()` + `_excute_edges()`）

**深度优先遍历**（DFS）：
1. 对当前页面调用 `_excute_edges(page_node)`：
   - 依次执行每条边（widget 操作：click/input）
   - 执行动作后 `dump_page(refresh=True)` 获取新页面
   - 调用 `_is_page_exist()` 判断是否新页面
   - 若是新页面 → 创建新 `PageNode`，**异步提交** `get_widgets_from_page()` 任务到线程池（4 workers）
   - 若已存在 → 直接链接到已有节点
2. `get_widgets_from_page()`：将前后截图 + 动作描述发给 LLM，获取该页面的所有交互控件的 JSON 描述（含 description/action/position/is_leaf/postcondition）
3. 对**非叶子节点**（`is_leaf=False`）递归进入 `_explore()`，深度上限 10
4. 回溯时执行 `back()` 尝试返回父页面，失败时 **重启 App + 重播路径**（通过 BFS 找到最短路径，最多尝试 3 次 back，然后 fallback 到 restart）

**坐标系统**：LLM 输出归一化坐标（0~1000），在 `_excute_action()` 中转换为真实像素坐标：
```python
real_pos = (int(parsed_pos[0] / 1000 * image_width),
            int(parsed_pos[1] / 1000 * image_height))
```

**Widget 重定位**：每次点击前，将当前截图 + widget 描述发给 LLM 获取精确坐标（`get_position_prompt`），防止因页面滚动/布局变化导致坐标失效。最多重试 3 次。

**Activity 覆盖度追踪**：每 60 秒自动记录一次 `activity_coverage.json` 和 `activity_coverage_history.jsonl`。

##### Phase 2: FDG 构建（`build_FDG()`）

读取 PTG JSON，BFS 遍历 PTG 边，区分每条边是"同一功能内步骤"还是"新功能起点"：

1. **并行边分类**（10 workers）：
   - 对每条 PTG 边，将前后截图 + 动作描述发给 LLM（`page_to_page_prompt`）
   - LLM 返回 `{new_functional_point: bool, data_in: [...], data_out: [...]}`
2. **相同功能** → 将 `action_ref` 追加到当前 `FDGNode`
3. **新功能** → 创建新 `FDGNode`，调用 `get_function_description()` 获取语义描述，入队继续 BFS
4. BFS 过程中通过 `expanded_state` 集合 + `page_path` 环检测防止无限循环
5. 最后，对每个 FDGNode 调用 `extract_core_logic_for_fdg()`：
   - 将属于该功能的所有 action_refs + 关键页面截图发给 LLM（`FDG_CORE_LOGIC_PROMPT`）
   - LLM 返回结构化 JSON：`{entry_page, logic, steps: [{id, action_ref, summary}], flow_edges, branch_points}`
   - 这就是该功能的**流程图式核心逻辑**

**边分类的核心原理**（`page_to_page_prompt`）：
- 新功能点：全屏页面跳转、Tab/模块切换、Modal/对话框、底部面板、侧边抽屉
- 非新功能点：内联 UI 变化（展开手风琴）、简单输入、下拉选择、Toast/Loading、滚动
- data_in/out 要求使用**具体的抽象实体名**，禁止模糊术语

##### Phase 3: 数据依赖推断（`build_FDG_with_dependency()`）

1. 收集所有 FDG 节点（`to_test=True` 且有 data_in/out）
2. 将它们作为 JSON 发给 LLM（`data_flow_prompt`）
3. LLM 返回 `{"data_dependencies": {"consumer_idx": [producer_idx, ...], ...}}`
4. 匹配规则：如果节点 j 的 `data_in` 与节点 i 的 `data_out` 语义等价 → `i → j`
5. 结果写入 `fdg_with_data_dep.json`

##### Phase 4: 测试

**三级测试**（均在 `task_level_test()` 和 `app_level_test()` 中规划好但执行部分被注释掉了——当前版本以生成测试计划为主）：

1. **Widget 级**（`widget_level_test()`）：对标记为 `type='widget'` 的节点生成单控件测试流
2. **Task 级**（`task_level_test()`）：
   - 对每个 `to_test=True` 的 FDG 节点，将其 `core_logic` 作为主任务
   - 调用 LLM 生成 2~3 个**变体路径**（分支变异、顺序变异、重复/省略、边界输入）
   - 执行主路径和变体路径
3. **App 级**（`app_level_test()`）：
   - 遍历所有 (`producer_idx`, `consumer_idx`) 依赖对
   - 对每对，调用 LLM 生成 1~2 个**跨功能测试用例**（先执行 Producer 创建/更新数据，再执行 Consumer 使用/显示数据）
   - 最多 5 个测试用例每对

##### Phase 5: Bug 检测（双通道）

**通道 1：实时检测**（`_detect_bug_once()`）
- 在 `_excute_edges()` 每执行一个动作后，将 (before_image, after_image, action_description) 入队
- 后台线程消费队列，调用 LLM（`bug_detection_prompt`）判断是否有 bug
- 检测类型：crash（显式崩溃对话框 / 进程退出到桌面）、functional（操作无效果 / 数据错误 / 数据缺失/冗余）
- 排除项：视觉/布局差异、导航到意外页面（除非导致崩溃）、提示/警告/Toast 消息、加载空白页
- 发现 bug 后保存 `before.png` + `after.png` + `bug.json` 到 `output/bugN/`

**通道 2：路径级检测**（`detect_bug_from_path_record()`）
- 在功能测试完成后，将完整的执行序列（截图 + 步骤描述）发给 LLM（`path_bug_detection_prompt`）
- 拥有更完整的上下文，可以检测步骤间的累积 bug

#### 3.3.4 动作解析器（`action_parser.py`）

将 LLM 返回的文本解析为结构化动作字典：
```
"Action: click(point='<point>123 456</point>')"
→ {"action": "click", "point": (123, 456), ...}
```
支持 6 种动作：`click`, `long_click`, `input`（含 point+content 两个参数）、`scroll`（含 direction）、`press_back`、`finished`

### 3.4 顶层编排（`hmbot.py`）

`HMBot` 类提供多设备并发探索框架（当前代码中 `explore()` 方法仍为单设备串行）。支持的探索模式：
- `ExploreGoal.HARDWARE`：硬件资源测试（value=资源类型，如 audio/camera）
- `ExploreGoal.TESTCASE`：测试脚本执行（value=脚本路径）

### 3.5 辅助模块

#### 3.5.1 知识库（`knowledge.py`, `database.py`）
- `KnowledgeBaseRetriever`：基于 `BAAI/bge-base-en-v1.5` 的句子嵌入，从 case 目录中构建向量索引，支持 bug 二次确认（在代码中**已注释掉**）
- `BugKnowledgeBase`：基于 `paraphrase-multilingual-MiniLM-L12-v2` 的 bug 报告检索（从 Excel 构建），支持知识共享

#### 3.5.2 图像工具（`cv.py`）
- `encode_image()`：将 OpenCV 图像缩放到 ≤800×1400 → JPEG 编码 → Base64，用于 LLM API 传输
- `combine_images_horizontal()`：多张图片水平拼接（用于复合展示）

---

## 四、完整数据流

```
APK 文件
  │
  ▼
[AndroidApp 解析] → package_name, entry_activity, activities[], app_name
  │
  ▼
[Device 连接] → ADB + U2 (uiautomator2)
  │
  ▼
[Explorer.explore()] — Phase 1: PTG 构建
  │  dump_page() → Page{vht, img, vht_hash, img_hash, info}
  │  LLM 提取 widgets → edges[]
  │  页面去重（hash + LLM）
  │  DFS 遍历，深度=10
  │  ▼
  │  save_PTG() → ptg_report_*.json + pages_*/screenshot.png + vht.json
  │
  ▼
[Explorer.build_FDG()] — Phase 2: FDG 构建
  │  read_PTG() → page_nodes[]
  │  BFS + LLM 边分类（并行 10 workers）
  │  data_in/data_out 提取
  │  core_logic 提取（流程图结构）
  │  ▼
  │  save_FDG() → fdg.json
  │
  ▼
[Explorer.build_FDG_with_dependency()] — Phase 3: 数据依赖
  │  read_FDG()
  │  LLM 推断生产者→消费者关系
  │  ▼
  │  save_FDG() → fdg_with_data_dep.json
  │
  ▼
[Explorer.task_level_test()] — Phase 4a: 功能内测试
  │  对每个 FDG 节点：
  │    core_logic → 主任务 + 2~3 变体路径
  │    _test_function() → LLM 驱动的闭环测试循环（max 20 步）
  │    detect_bug_from_path_record()
  │
  ▼
[Explorer.app_level_test()] — Phase 4b: 跨功能测试
  │  对每对 (producer, consumer)：
  │    LLM 规划跨功能测试用例
  │    先执行 producer → 再执行 consumer
  │    detect_bug_from_path_record()
  │
  ▼
输出产物：
  output/
  ├── ptg_report_*.json          # PTG
  ├── fdg.json                   # FDG
  ├── fdg_with_data_dep.json     # 带数据依赖的 FDG
  ├── activity_coverage.json     # Activity 覆盖率
  ├── activity_coverage_history.jsonl
  ├── LLM-Token-Stats.json       # Token 消耗
  ├── bug1/                      # 发现的 bug
  │   ├── before.png
  │   ├── after.png
  │   └── bug.json
  └── pages_*/                   # 各页面的截图和 UI 树
```

---

## 五、复现实验完整步骤

### 5.1 环境准备

#### 硬件要求
- 一台 **Android 真机**（Android 5.0+，推荐 Android 10+）
- USB 数据线（确保支持数据传输，非仅充电线）
- 一台装有 **Ubuntu 24.04**（或 Windows/macOS）的电脑

#### 软件要求
- Python 3.9+
- Java JDK 17+（Android SDK 依赖）
- ADB（Android Platform Tools）
- Git

### 5.2 步骤 1：获取代码

```bash
git clone https://github.com/EdgarRhys/FuncDroid_Full.git
cd FuncDroid_Full
```

> 注意：本仓库仅含核心代码。完整数据集和实验产物在 `FuncDroid_Full` 仓库。

### 5.3 步骤 2：一键环境搭建（推荐）

```bash
chmod +x setup_funcdroid.sh
./setup_funcdroid.sh
```

该脚本会自动完成：
1. 检查 Ubuntu 版本
2. 安装系统依赖（Java、Python、图形库等）
3. 下载并配置 ADB
4. 创建 Python 虚拟环境
5. 安装 `requirements.txt` 中所有依赖
6. 修复兼容性问题（创建 `hmbot → funcdroid` 符号链接、`findstr → grep` 等）
7. **交互式配置 LLM API**（支持豆包、GPT-4o 中转、通义千问或自定义）
8. 连接手机（ADB）
9. 初始化 uiautomator2（手机上安装 ATX 守护 APK）
10. 运行设备验证

### 5.4 步骤 3：手动环境搭建（备选）

```bash
# 3.1 系统依赖
sudo apt update
sudo apt install -y wget curl git unzip zip \
    openjdk-17-jdk openjdk-17-jre \
    python3 python3-pip python3-venv \
    libgl1 libglib2.0-0t64 libsm6 libxext6 libxrender-dev libxcb1 \
    ffmpeg libxcb-xinerama0

# 3.2 ADB
cd /tmp
wget https://dl.google.com/android/repository/platform-tools-latest-linux.zip
unzip platform-tools-latest-linux.zip -d ~/
echo 'export PATH="$HOME/platform-tools:$PATH"' >> ~/.bashrc
source ~/.bashrc

# 3.3 Python 虚拟环境
cd FuncDroid
python3 -m venv venv
source venv/bin/activate

# 3.4 依赖安装（逐个安装以处理失败情况）
pip install --upgrade pip
pip install -r requirements.txt
# 如果 torch 等大包安装失败，可尝试：
# pip install torch --index-url https://download.pytorch.org/whl/cpu

# 3.5 修复 hmbot 导入问题
ln -sf funcdroid hmbot

# 3.6 修复 Linux 兼容性问题
sed -i 's/| findstr mCurrentFocus/| grep mCurrentFocus/' funcdroid/explorer/explorer.py
```

### 5.5 步骤 4：配置 LLM API

创建 `funcdroid/.env` 文件：

```bash
# 方案 A：使用豆包 Vision + DeepSeek
SPECIALIZED_BASE_URL="https://ark.cn-beijing.volces.com/api/v3/"
SPECIALIZED_MODEL="doubao-seed-1-6-vision-250815"
SPECIALIZED_API_KEY="你的豆包API-Key"

# 方案 B：使用 GPT-4o 中转代理
# SPECIALIZED_BASE_URL="https://your-proxy.com/v1/"
# SPECIALIZED_MODEL="gpt-4o"
# SPECIALIZED_API_KEY="your-api-key"

# 方案 C：使用通义千问
# SPECIALIZED_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1/"
# SPECIALIZED_MODEL="qwen-vl-max"
# SPECIALIZED_API_KEY="your-dashscope-key"
```

同时编辑 `funcdroid/explorer/llm.py` 中的 `client_llm`（如有需要，当前代码中未使用此 client）：

```python
client_llm = OpenAI(
    base_url="https://api.deepseek.com/v1/",
    api_key="your-deepseek-key",
)
```

**测试 LLM 连通性**：
```bash
python test.py
# 应输出：[OK] General LLM: OK 和 [OK] Specialized LLM: OK
```

### 5.6 步骤 5：连接手机并验证

```bash
# 1. 手机开启"开发者选项"和"USB 调试"
# 2. 连接 USB 线，手机上点击"允许 USB 调试"
adb devices
# 应显示：XXXXX   device

# 3. 初始化 uiautomator2
python3 -m uiautomator2 init
# 手机上会自动安装两个 APK（ATX 守护进程），点击"安装"/"允许"

# 4. 验证
python verify_device.py
# 应全部通过：设备连接、uiautomator2、截图、UI 树、按键操作
```

### 5.7 步骤 6：准备测试 APK

准备一个待测试的 Android APK 文件。建议选择：
- 中小型开源 App（如 Simple Notes、Tasks 等）
- 避免选择有加固保护的 App（androguard 无法解析）
- 确保 APK 的 targetSdk 与手机 Android 版本兼容

### 5.8 步骤 7：运行完整测试流水线

```bash
# 方式 A：一键运行（推荐）
./run_funcdroid.sh /path/to/app.apk ./output 3600
# 参数：APK路径  输出目录  超时秒数（3600=1小时）

# 方式 B：Python 程序化运行
source venv/bin/activate
python3 -c "
import sys, os, time
sys.path.insert(0, '.')

from hmbot.device.device import Device
from hmbot.utils.proto import OperatingSystem
from hmbot.utils.utils import get_android_available_devices
from hmbot.app.android_app import AndroidApp
from hmbot.explorer.explorer import Explorer
from hmbot.explorer.utils import grant_all_permissions

# 获取设备
devices = get_android_available_devices()
device = Device(devices[0], OperatingSystem.ANDROID)

# 解析并安装 APK
app = AndroidApp(app_path='your_app.apk')
device.install_app(app)
time.sleep(5)
grant_all_permissions(app.package_name)
device.start_app(app)
time.sleep(10)

# 开始探索
explorer = Explorer(device=device, app_name=app.app_name, app=app)
explorer.time_limit_seconds = 3600
explorer.full_explorer(output_dir='./output')
"
```

### 5.9 步骤 8：查看结果

运行完成后，`./output/` 目录下将包含：

```
output/<serial>/
├── ptg_report_YYYYMMDD_HHMMSS.json   # PTG（页面转换图）
├── fdg.json                           # FDG（功能流程图）
├── fdg_with_data_dep.json             # 带数据依赖的 FDG
├── activity_coverage.json             # Activity 覆盖率
├── activity_coverage_history.jsonl    # 覆盖率历史
├── LLM-Token-Stats.json               # LLM Token 消耗统计
├── bug1/                              # 发现的 Bug #1
│   ├── before.png                     #   操作前截图
│   ├── after.png                      #   操作后截图
│   └── bug.json                       #   Bug 详情 JSON
├── bug2/ ...
└── pages_YYYYMMDD_HHMMSS/            # 各页面的截图和 UI 树
    ├── 0/
    │   ├── screenshot.png
    │   └── vht.json
    └── 1/ ...
```

**解读指标**：
- `activity_coverage.json` 中的 `activity_coverage`：探索达到的 Activity 覆盖率
- `LLM-Token-Stats.json` 中的 `total_tokens`：总 LLM 消耗
- `bugN/` 的个数：发现的 bug 数量，每个 `bug.json` 中有 `has_bug`、`bug_type`（crash/functional）、`bug_description`
- `fdg.json` 中的 `FDG` 数组长度：识别到的功能点数量

### 5.10 步骤 9：分析特定指标

```bash
# 查看 Activity 覆盖率
cat output/<serial>/activity_coverage.json | python3 -m json.tool

# 统计发现的 Bug
find output/<serial>/ -name "bug.json" | wc -l

# 查看 FDG 功能点数
python3 -c "import json; d=json.load(open('output/<serial>/fdg.json')); print(f'功能点数: {len(d[\"FDG\"])}')"

# 查看 Token 消耗
cat output/<serial>/LLM-Token-Stats.json
```

### 5.11 实验评估数据

完整仓库 `FuncDroid_Full` 中包含：
- `Effectiveness evaluation/`：有效性评估实验的输出和数据
- `Usefulness evaluation/`：实用性评估实验的输出和数据

这些数据集包含在多个真实 App 上运行的结果，可用于对比分析。

---

## 六、关键参数与调优建议

| 参数 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `time_limit_seconds` | `Explorer.__init__` | 3600 | 总探索时间上限（秒） |
| `depth_limit` | `Explorer.__init__` | 10 | DFS 最大深度 |
| `max_workers` (edges) | `build_FDG()` | 10 | FDG 边分类并行度 |
| `max_workers` (page) | `Explorer.__init__` | 4 | 页面 widget 提取并行度 |
| `SIMILARITY_THRESHOLD_MATCH` | `explorer.py` | 0.95 | imagehash 匹配阈值 |
| `VHT_WEIGHT` / `IMG_WEIGHT` | `explorer.py` | 0 / 1 | 页面相似度权重（当前仅用图像哈希） |
| `encode_image()` max_size | `cv.py` | (800, 1400) | 截图发给 LLM 前的最大尺寸 |
| LLM temperature | `llm.py` | 0 | 所有 LLM 调用温度为 0（确定性输出） |
| `_act_cov_interval_sec` | `Explorer.__init__` | 60 | Activity 覆盖率记录间隔 |

### 调优建议
- **加快探索速度**：减少 `depth_limit`（如 5）、增大 `max_workers`
- **提高页面识别精度**：将 `IMG_WEIGHT` 设为 0.5（同时使用 VHT 和图像特征）
- **节省 Token**：降低截图分辨率（修改 `max_size` 参数）
- **提高 Bug 检出率**：在 `_detect_bug_once()` 和 `detect_bug_from_path_record()` 中取消知识库复查逻辑的注释

---

## 七、已知限制与注意事项

1. **`client_llm` 未被使用**：`llm.py` 中定义了 `client_llm`，但所有实际调用都走 `client_uitars`。如需分离文本推理和视觉理解，需修改各调用点的函数选择。

2. **硬编码路径**：
   - `explorer.py:703`：`build_FDG_with_dependency()` 中 Token 统计输出路径硬编码为 `C:\\Users\\23314\\Desktop\\Fim\\output`
   - `knowledge.py:15`：`KB_ROOT` 硬编码为 `C:\\Users\\23314\\Desktop\\FuncDroid_new\\knowledge_base`
   - 移植到新环境时需修改或删除这些硬编码

3. **测试执行被注释**：`task_level_test()` 和 `app_level_test()` 中核心执行代码被注释（`self._replay_to_page()` 和 `self._test_function()` 调用），当前版本只生成测试计划而不实际执行。

4. **back() 退不回去**：回溯时如果 back() 失败，需重启 App + 重播路径，在深度测试中可能消耗大量时间。

5. **不支持模拟器**：代码假设使用真机（uiautomator2），在 Android 模拟器上运行可能需要调整 input 方法和截图方式。

6. **依赖重包**：`requirements.txt` 包含 `torch`、`transformers`、`sentence-transformers` 等大包，首次安装可能耗时 10~20 分钟。
