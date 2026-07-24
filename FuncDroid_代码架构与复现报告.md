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

#### 3.3.2 提示词模块（`prompt.py`）

约 15 个精心设计的 prompt template，按用途分类：

| Prompt | 用途 | 关键约束 |
|--------|------|----------|
| `get_widgets_from_page_prompt` | 从前后页面对比中提取新增交互控件 | 只识别新增控件、同类去重（保留代表）、排除系统 UI |
| `initial_page_prompt` | 首页控件识别 | 特殊规则：底部 Tab 栏必须全部枚举 |
| `test_function_prompt` | 指导 Agent 执行一个功能测试任务 | 支持 click/input/long_click/press_back/finished |
| `bug_detection_prompt` | 实时 bug 检测（探索过程中） | 区分 crash bug 和 functional bug |
| `path_bug_detection_prompt` | 事后路径级 bug 检测（测试完成后） | 相同分类但从序列角度判断 |
| `bug_recheck_prompt` | 结合知识库二次确认 | 更保守，宁可漏报不可误报 |
| `page_exist_prompt` | 页面去重的最后手段（LLM 视觉比对） | 结构相同但内容不同 = 同一页面 |
| `FDG_function_description_prompt` | 为 FDG 节点生成功能描述 | 结合导航路径上下文 |
| `page_to_page_prompt` | 边分类：是否新建功能节点 + data_in/data_out | 严格的导航/数据分离规则 |
| `page_to_widget_prompt` | Widget 级功能点判断 | widget 组内去重 |
| `data_flow_prompt` | 推断 FDG 节点间数据依赖 | 高召回策略（语义等价的实体视为匹配） |
| `data_flow_prompt_without_data` | 同上但无 data_in/out（仅从描述推断） | 高精度策略（宁可少不可错） |
| `task_planning_prompt` | 生成变体测试路径 | 主路径 + 2~3 变体（边界/异常） |
| `get_position_prompt` | Widget 重定位（点击前确认坐标） | 返回 [x, y] 或 [0, 0] |

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
