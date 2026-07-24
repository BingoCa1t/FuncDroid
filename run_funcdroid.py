#!/usr/bin/env python3
"""
FuncDroid 一键运行脚本 (Python 原生版)
========================================
替代 run_funcdroid.sh，提供逐阶段的详细进度、输入/输出追踪和错误处理。

用法:
    python run_funcdroid.py <APK路径> [--output ./output] [--timeout 3600]
    python run_funcdroid.py ./myapp.apk --output ./results --timeout 1800

前置条件:
    1. ADB 已安装且手机已连接 (adb devices 可见)
    2. uiautomator2 已初始化 (python3 -m uiautomator2 init)
    3. funcdroid/.env 已配置 (SPECIALIZED_BASE_URL, API_KEY)
    4. Python 虚拟环境已激活 (可选但推荐)
"""

import sys
import os
import time
import json
import shutil
import subprocess
import argparse
from pathlib import Path
from datetime import datetime, timedelta


# ═══════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════

class Colors:
    """ANSI 颜色码 (终端友好)"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'


def banner(title: str, width: int = 66):
    """打印带分隔线的阶段标题"""
    print()
    print(f"{Colors.BOLD}{Colors.CYAN}{'=' * width}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}  {title}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'=' * width}{Colors.RESET}")
    print()


def phase_header(phase_num: int, total: int, name: str):
    """打印阶段头部"""
    print()
    line = f"══ Phase {phase_num}/{total}: {name} ══"
    pad = 66 - len(line)
    left_pad = pad // 2
    right_pad = pad - left_pad
    print(f"{Colors.BOLD}{Colors.BLUE}{'─' * left_pad}{line}{'─' * right_pad}{Colors.RESET}")
    print(f"{Colors.DIM}  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Colors.RESET}")


def phase_footer(success: bool, elapsed: float, detail: str = ""):
    """打印阶段尾部"""
    status = f"{Colors.GREEN}✓ 成功{Colors.RESET}" if success else f"{Colors.RED}✗ 失败{Colors.RESET}"
    elapsed_str = timedelta(seconds=int(elapsed))
    print(f"  {status}  耗时: {elapsed_str}  {detail}")
    print(f"{Colors.DIM}  结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Colors.RESET}")
    print()


def step(msg: str):
    """打印子步骤"""
    print(f"  {Colors.CYAN}→{Colors.RESET} {msg}")


def step_ok(msg: str = ""):
    """子步骤成功"""
    print(f"  {Colors.GREEN}  ✓{Colors.RESET} {msg}")


def step_warn(msg: str):
    """子步骤警告"""
    print(f"  {Colors.YELLOW}  ⚠{Colors.RESET} {msg}")


def step_err(msg: str):
    """子步骤错误"""
    print(f"  {Colors.RED}  ✗{Colors.RESET} {msg}")


def file_info(path: str, label: str = ""):
    """打印文件信息"""
    p = Path(path)
    if p.exists():
        size_kb = p.stat().st_size / 1024
        label_str = f" ({label})" if label else ""
        print(f"  {Colors.GREEN}  ✓{Colors.RESET} {Colors.DIM}{p.name}{Colors.RESET}{label_str}  [{size_kb:.1f} KB]")
        return True
    else:
        print(f"  {Colors.YELLOW}  ✗{Colors.RESET} {Colors.DIM}{p.name}{Colors.RESET}  (未生成)")
        return False


def run_cmd(cmd, timeout=30):
    """运行外部命令并返回 (returncode, stdout, stderr)"""
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"命令超时 ({timeout}s): {cmd}"
    except Exception as e:
        return -1, "", str(e)


# ═══════════════════════════════════════════════════════════════════════
# 0. 前置校验
# ═══════════════════════════════════════════════════════════════════════

def validate_prerequisites(args, project_root: Path):
    """逐一校验运行所需的前置条件，返回 bool + 信息列表"""
    banner("0. 前置条件校验")
    all_ok = True
    issues = []

    # 0.1 APK 存在性
    step(f"检查 APK 文件: {args.apk}")
    apk_path = Path(args.apk)
    if apk_path.exists():
        step_ok(f"文件大小 {apk_path.stat().st_size / (1024*1024):.1f} MB")
    else:
        step_err(f"文件不存在: {args.apk}")
        all_ok = False
        issues.append("APK 文件不存在")

    # 0.2 ADB 可用
    step("检查 ADB 环境")
    rc, out, err = run_cmd("adb version", timeout=10)
    if rc == 0 and "Android Debug Bridge" in out:
        version_line = out.splitlines()[0] if out else "unknown"
        step_ok(version_line)
    else:
        step_err("adb 不在 PATH 中或不可用")
        step_err("请安装 Android Platform-Tools: https://developer.android.com/studio/releases/platform-tools")
        all_ok = False
        issues.append("ADB 不可用")

    # 0.3 设备连接
    step("检查设备连接")
    rc, out, err = run_cmd("adb devices", timeout=10)
    if rc != 0:
        step_err("adb devices 执行失败")
        all_ok = False
        issues.append("adb devices 失败")
    else:
        device_lines = [l for l in out.splitlines() if l.strip().endswith("device")]
        if not device_lines:
            step_err("未检测到已授权设备")
            step("请确认: 1) USB 已连接  2) USB 调试已开启  3) 手机上已点击'允许'")
            all_ok = False
            issues.append("未检测到设备")
        else:
            serials = [l.split()[0] for l in device_lines]
            if len(serials) > 1:
                step_warn(f"检测到 {len(serials)} 台设备: {serials}")
                step(f"将使用第一台设备: {serials[0]}")
            step_ok(f"设备序列号: {serials[0]}")
            step("设备详情:")
            for prop in ['ro.product.brand', 'ro.product.model', 'ro.build.version.release', 'ro.build.version.sdk']:
                rc2, out2, _ = run_cmd(f"adb -s {serials[0]} shell getprop {prop}", timeout=10)
                if rc2 == 0 and out2:
                    print(f"      {prop.split('.')[-1]}: {out2}")

    # 0.4 Python 包检查
    step("检查关键 Python 依赖")
    required_modules = {
        "uiautomator2": "pip install uiautomator2",
        "openai": "pip install openai",
        "cv2": "pip install opencv-python",
        "numpy": "pip install numpy",
        "androguard": "pip install androguard",
        "loguru": "pip install loguru",
        "dotenv": "pip install python-dotenv",
    }
    missing = []
    for mod, install_cmd in required_modules.items():
        import_name = "cv2" if mod == "cv2" else mod
        try:
            __import__(import_name)
        except ImportError:
            missing.append(f"{mod} ({install_cmd})")

    if missing:
        step_err(f"缺少 {len(missing)} 个依赖:")
        for m in missing:
            step_err(f"  • {m}")
        all_ok = False
        issues.append(f"缺少 {len(missing)} 个依赖")
    else:
        step_ok("所有关键依赖已安装")

    # 0.5 hmbot 符号链接
    step("检查 hmbot → funcdroid 导入路径")
    hmbot_dir = project_root / "hmbot"
    funcdroid_dir = project_root / "funcdroid"
    if hmbot_dir.exists():
        if hmbot_dir.is_symlink():
            target = os.readlink(str(hmbot_dir))
            step_ok(f"符号链接已存在: hmbot → {target}")
        else:
            step_warn("hmbot 以普通目录存在 (非符号链接), 可能不是最新代码")
    else:
        step("创建符号链接: hmbot → funcdroid")
        try:
            os.symlink(str(funcdroid_dir), str(hmbot_dir), target_is_directory=True)
            step_ok("符号链接已创建")
        except OSError as e:
            step_err(f"创建符号链接失败: {e}")
            step("请手动执行: ln -sf funcdroid hmbot  (Linux/macOS)")
            step("或:  mklink /D hmbot funcdroid        (Windows)")
            all_ok = False
            issues.append("无法创建 hmbot 符号链接")

    # 0.6 .env 文件
    step("检查 LLM API 配置 (.env)")
    env_file = funcdroid_dir / ".env"
    if env_file.exists():
        step_ok(f".env 文件存在")
        # 手动解析 .env (避免 python-dotenv 版本兼容问题)
        try:
            env_vals = {}
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    env_vals[key] = val
            has_url = bool(env_vals.get("SPECIALIZED_BASE_URL"))
            has_key = bool(env_vals.get("SPECIALIZED_API_KEY"))
            has_model = bool(env_vals.get("SPECIALIZED_MODEL"))
            if has_url and has_key and has_model:
                step_ok(f"SPECIALIZED_BASE_URL: 已配置")
                step_ok(f"SPECIALIZED_MODEL: {env_vals.get('SPECIALIZED_MODEL')}")
                step_ok(f"SPECIALIZED_API_KEY: {'*' * 8} (已配置)")
            else:
                missing_env = []
                if not has_url: missing_env.append("SPECIALIZED_BASE_URL")
                if not has_key: missing_env.append("SPECIALIZED_API_KEY")
                if not has_model: missing_env.append("SPECIALIZED_MODEL")
                step_err(f".env 中缺少必要字段: {', '.join(missing_env)}")
                all_ok = False
                issues.append(".env 配置不完整")
        except Exception as e:
            step_warn(f"无法解析 .env: {e}")
    else:
        step_err(f".env 文件未找到: {env_file}")
        step(f"请创建 {env_file} 并配置以下字段:")
        step("  SPECIALIZED_BASE_URL=https://your-api-endpoint/v1/")
        step("  SPECIALIZED_MODEL=your-model-name")
        step("  SPECIALIZED_API_KEY=sk-your-key")
        all_ok = False
        issues.append(".env 文件缺失")

    # 0.7 输出目录
    step(f"检查输出目录: {args.output}")
    output_dir = Path(args.output)
    if output_dir.exists():
        existing_items = list(output_dir.iterdir())
        if existing_items:
            step_warn(f"输出目录已存在且非空 ({len(existing_items)} 项), 旧文件可能被覆盖")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        step_ok("输出目录已创建")

    # 0.8 检查 uiautomator2 是否已初始化
    step("检查 uiautomator2 初始化状态")
    rc, out, _ = run_cmd("adb shell pm list packages com.github.uiautomator", timeout=10)
    if "com.github.uiautomator" in out:
        step_ok("uiautomator2 ATX 守护进程已安装")
    else:
        step_err("uiautomator2 未初始化")
        step("请执行: python3 -m uiautomator2 init")
        all_ok = False
        issues.append("uiautomator2 未初始化")

    # --- 汇总 ---
    print()
    if all_ok:
        print(f"  {Colors.GREEN}{Colors.BOLD}✓ 所有前置条件检查通过 ({len(issues)} 个问题){Colors.RESET}")
    else:
        print(f"  {Colors.RED}{Colors.BOLD}✗ 前置条件校验未通过，共 {len(issues)} 个问题:{Colors.RESET}")
        for i, issue in enumerate(issues, 1):
            print(f"    {Colors.RED}{i}. {issue}{Colors.RESET}")
        print()
    return all_ok


# ═══════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="FuncDroid 一键运行脚本 — 分阶段执行 IFO 测试流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_funcdroid.py ./app.apk
  python run_funcdroid.py ./app.apk --output ./results --timeout 3600
  python run_funcdroid.py ./app.apk --timeout 1800 --debug
        """
    )
    parser.add_argument("apk", help="待测试的 APK 文件路径")
    parser.add_argument("--output", "-o", default="./output", help="输出目录 (默认: ./output)")
    parser.add_argument("--timeout", "-t", type=int, default=3600, help="总探索超时秒数 (默认: 3600)")
    parser.add_argument("--debug", "-d", action="store_true", help="开启 debug 模式 (更多输出)")
    parser.add_argument("--phase", "-p", choices=["all", "explore", "fdg", "test"], default="all",
                        help="指定运行阶段 (默认: all)")
    args = parser.parse_args()

    # ── 全局计时 ──────────────────────────────────────────────
    global_start = time.time()
    project_root = Path(__file__).resolve().parent

    # ── 启动横幅 ──────────────────────────────────────────────
    banner("FuncDroid Automated Testing Pipeline v2.0")
    print(f"  APK:      {Colors.BOLD}{args.apk}{Colors.RESET}")
    print(f"  输出目录: {Colors.BOLD}{args.output}{Colors.RESET}")
    print(f"  超时限制: {Colors.BOLD}{args.timeout}s ({args.timeout//60} 分钟){Colors.RESET}")
    print(f"  运行阶段: {Colors.BOLD}{args.phase}{Colors.RESET}")
    print(f"  项目目录: {Colors.BOLD}{project_root}{Colors.RESET}")
    print(f"  Debug:    {Colors.BOLD}{'是' if args.debug else '否'}{Colors.RESET}")

    # ── 0. 前置校验 ───────────────────────────────────────────
    if not validate_prerequisites(args, project_root):
        print(f"\n{Colors.RED}请修复以上问题后重新运行。{Colors.RESET}")
        sys.exit(1)

    # ── 切换工作目录 ──────────────────────────────────────────
    os.chdir(str(project_root))
    sys.path.insert(0, str(project_root))

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 获取设备序列号 ────────────────────────────────────────
    rc, out, _ = run_cmd("adb devices")
    device_serial = [l.split()[0] for l in out.splitlines()
                     if l.strip().endswith("device")][0]
    print(f"\n  {Colors.GREEN}设备已就绪: {device_serial}{Colors.RESET}")

    # ── 导入 FuncDroid 模块 ───────────────────────────────────
    step("加载 FuncDroid 模块...")
    try:
        from hmbot.device.device import Device
        from hmbot.utils.proto import OperatingSystem
        from hmbot.app.android_app import AndroidApp
        from hmbot.explorer.explorer import Explorer
        from hmbot.explorer.utils import grant_all_permissions
        step_ok("所有模块加载成功")
    except ImportError as e:
        step_err(f"模块导入失败: {e}")
        step("请确认 hmbot → funcdroid 符号链接已创建")
        step("  ln -sf funcdroid hmbot")
        sys.exit(1)

    # ── 解析 APK ──────────────────────────────────────────────
    banner("APK 解析")
    step(f"解析: {args.apk}")
    app = AndroidApp(app_path=str(Path(args.apk).resolve()))
    print(f"  {Colors.BOLD}应用名称:{Colors.RESET}     {app.app_name}")
    print(f"  {Colors.BOLD}包名:{Colors.RESET}         {app.package_name}")
    print(f"  {Colors.BOLD}入口 Activity:{Colors.RESET} {app.entry_ability}")
    print(f"  {Colors.BOLD}声明的 Activities:{Colors.RESET} {len(app.abilities)} 个")
    if args.debug:
        for a in app.abilities[:10]:
            print(f"      • {a}")
        if len(app.abilities) > 10:
            print(f"      ... 共 {len(app.abilities)} 个")

    # ── 初始化设备 ────────────────────────────────────────────
    banner("设备初始化")
    step(f"连接设备: {device_serial}")
    device = Device(device_serial, OperatingSystem.ANDROID)
    step_ok("设备对象已创建 (Connector: ADB, Automator: uiautomator2)")

    step(f"卸载旧版本 (如果存在): {app.package_name}")
    try:
        device.uninstall_app(app)
        step_ok("旧版本已卸载")
    except Exception:
        step_ok("无需卸载 (首次安装)")

    step(f"安装 APK...")
    device.install_app(app)
    step_ok("APK 安装完成")

    step("授予运行时权限...")
    grant_all_permissions(app.package_name)
    step_ok("权限已授予")

    step("启动应用...")
    device.start_app(app)
    time.sleep(10)
    step_ok("应用已启动")

    step("确认前台页面...")
    page = device.dump_page(refresh=True)
    if page and page.info:
        step_ok(f"当前页面: {page.info.bundle} / {page.info.ability}")
    else:
        step_warn("无法确认前台页面状态")

    # ── 创建 Explorer ─────────────────────────────────────────
    step("创建 Explorer 实例...")
    explorer = Explorer(device=device, app_name=app.app_name, app=app)
    explorer.time_limit_seconds = args.timeout
    step_ok(f"Explorer 已创建 (超时: {args.timeout}s, bug 检测线程已启动)")

    # ═══════════════════════════════════════════════════════════
    # Phase 1: PTG 探索
    # ═══════════════════════════════════════════════════════════
    if args.phase in ("all", "explore"):
        phase_header(1, 4, "PTG 探索 (Page Transition Graph)")

        # ── 输入 ──────────────────────────────────────────────
        print(f"  {Colors.CYAN}┌─ 输入 ─────────────────────────────────────┐{Colors.RESET}")
        print(f"  {Colors.CYAN}│{Colors.RESET} App:       {app.app_name}")
        print(f"  {Colors.CYAN}│{Colors.RESET} Package:   {app.package_name}")
        print(f"  {Colors.CYAN}│{Colors.RESET} Activities:{len(app.abilities)} 个")
        print(f"  {Colors.CYAN}│{Colors.RESET} Timeout:   {args.timeout}s ({args.timeout//60} min)")
        print(f"  {Colors.CYAN}│{Colors.RESET} 深度上限:  {explorer.depth_limit}")
        print(f"  {Colors.CYAN}└──────────────────────────────────────────┘{Colors.RESET}")

        phase1_start = time.time()
        phase1_success = False
        try:
            explorer.explore(output_dir=str(output_dir))
            phase1_success = True
        except Exception as e:
            step_err(f"PTG 探索异常: {e}")
            if args.debug:
                import traceback; traceback.print_exc()

        phase1_elapsed = time.time() - phase1_start

        # ── 查找 PTG 输出文件 ─────────────────────────────────
        ptg_files = sorted(output_dir.glob("ptg_report_*.json"))
        ptg_file = ptg_files[-1] if ptg_files else None

        # 创建固定文件名链接 (修复 full_explorer 的命名不匹配 bug)
        fixed_ptg = output_dir / "ptg.json"
        if ptg_file and ptg_file != fixed_ptg:
            try:
                if fixed_ptg.exists() or fixed_ptg.is_symlink():
                    fixed_ptg.unlink()
                shutil.copy2(str(ptg_file), str(fixed_ptg))
            except Exception:
                pass  # 非致命

        # ── 输出 ──────────────────────────────────────────────
        print(f"\n  {Colors.CYAN}┌─ 输出 ─────────────────────────────────────┐{Colors.RESET}")
        if ptg_file:
            ptg_json = json.loads(ptg_file.read_text(encoding="utf-8"))
            nodes = ptg_json.get("nodes", [])
            explored = ptg_json.get("explored_abilities", [])
            print(f"  {Colors.CYAN}│{Colors.RESET} PTG 文件:      {Colors.GREEN}{ptg_file.name}{Colors.RESET}  (固定副本: ptg.json)")
            print(f"  {Colors.CYAN}│{Colors.RESET} 页面节点数:   {len(nodes)}")
            print(f"  {Colors.CYAN}│{Colors.RESET} 探索到的 Activity: {len(explored)} / {len(app.abilities)}")
            if explored:
                coverage = len(explored) / max(len(app.abilities), 1) * 100
                print(f"  {Colors.CYAN}│{Colors.RESET} Activity 覆盖率: {coverage:.1f}%")
        else:
            print(f"  {Colors.CYAN}│{Colors.RESET} PTG 文件:      {Colors.RED}未生成{Colors.RESET}")
        pages_dir = sorted(output_dir.glob("pages_*/"))
        if pages_dir:
            print(f"  {Colors.CYAN}│{Colors.RESET} 页面截图目录: {pages_dir[-1].name} ({sum(1 for _ in pages_dir[-1].rglob('*.png'))} 张截图)")
        activity_cov = output_dir / "activity_coverage.json"
        if activity_cov.exists():
            cov_data = json.loads(activity_cov.read_text(encoding="utf-8"))
            print(f"  {Colors.CYAN}│{Colors.RESET} Activity 覆盖率文件: 已生成")
            print(f"  {Colors.CYAN}│{Colors.RESET}   命中/声明: {cov_data.get('hit_count', '?')}/{cov_data.get('declared_count', '?')}")
        token_file = output_dir / "LLM-Token-Stats.json"
        if token_file.exists():
            tok = json.loads(token_file.read_text(encoding="utf-8")).get("token_stats", {})
            print(f"  {Colors.CYAN}│{Colors.RESET} LLM Token 消耗: {tok.get('calls', 0)} 次调用, {tok.get('total_tokens', 0):,} tokens")
        print(f"  {Colors.CYAN}└──────────────────────────────────────────┘{Colors.RESET}")

        # 统计 bug
        bug_count = len(list(output_dir.glob("bug*/bug.json")))
        if bug_count:
            print(f"\n  {Colors.RED}🐛 探索阶段检测到 {bug_count} 个疑似 Bug{Colors.RESET}")

        phase_footer(phase1_success, phase1_elapsed,
                     f"节点数={len(nodes) if ptg_file else 0}")

        if not phase1_success:
            print(f"\n{Colors.RED}Phase 1 失败，终止后续阶段。{Colors.RESET}")
            sys.exit(1)

    # ═══════════════════════════════════════════════════════════
    # Phase 2: FDG 构建
    # ═══════════════════════════════════════════════════════════
    if args.phase in ("all", "fdg"):
        phase_header(2, 4, "FDG 构建 (Functionality Flow Graph)")

        # ── 确认 PTG 输入 ─────────────────────────────────────
        fixed_ptg = output_dir / "ptg.json"
        if not fixed_ptg.exists():
            step_err("ptg.json 不存在，请在 Phase 1 成功完成后再运行 Phase 2")
            sys.exit(1)

        # ── 输入 ──────────────────────────────────────────────
        ptg_json = json.loads(fixed_ptg.read_text(encoding="utf-8"))
        nodes = ptg_json.get("nodes", [])
        total_edges = sum(len(n.get("edges", [])) for n in nodes)
        print(f"  {Colors.CYAN}┌─ 输入 ─────────────────────────────────────┐{Colors.RESET}")
        print(f"  {Colors.CYAN}│{Colors.RESET} PTG 文件:    ptg.json")
        print(f"  {Colors.CYAN}│{Colors.RESET} 页面节点数: {len(nodes)}")
        print(f"  {Colors.CYAN}│{Colors.RESET} 总边数:     {total_edges}")
        print(f"  {Colors.CYAN}│{Colors.RESET} LLM 任务:   对 {total_edges} 条边进行功能分类 (并行 10 workers)")
        print(f"  {Colors.CYAN}└──────────────────────────────────────────┘{Colors.RESET}")

        phase2_start = time.time()
        phase2_success = False
        try:
            step("BFS 遍历 PTG + LLM 边分类 (new_functional_point?) ...")
            explorer.build_FDG(str(fixed_ptg))

            fdg_file = output_dir / "fdg.json"
            if fdg_file.exists():
                fdg_data = json.loads(fdg_file.read_text(encoding="utf-8"))
                fdg_nodes = fdg_data.get("FDG", [])
                step_ok(f"FDG 构建完成: {len(fdg_nodes)} 个功能节点")
            phase2_success = True
        except Exception as e:
            step_err(f"FDG 构建异常: {e}")
            if args.debug:
                import traceback; traceback.print_exc()

        phase2_elapsed = time.time() - phase2_start

        # ── 输出 ──────────────────────────────────────────────
        print(f"\n  {Colors.CYAN}┌─ 输出 ─────────────────────────────────────┐{Colors.RESET}")
        fdg_file = output_dir / "fdg.json"
        if fdg_file.exists():
            fdg_data = json.loads(fdg_file.read_text(encoding="utf-8"))
            fdg_nodes = fdg_data.get("FDG", [])
            with_data = [n for n in fdg_nodes if n.get("data_in") or n.get("data_out")]
            with_core = [n for n in fdg_nodes if n.get("core_logic")]
            print(f"  {Colors.CYAN}│{Colors.RESET} FDG 文件:        {Colors.GREEN}fdg.json{Colors.RESET}")
            print(f"  {Colors.CYAN}│{Colors.RESET} 功能节点总数:    {len(fdg_nodes)}")
            print(f"  {Colors.CYAN}│{Colors.RESET} 含 data_in/out:  {len(with_data)}")
            print(f"  {Colors.CYAN}│{Colors.RESET} 含 core_logic:   {len(with_core)}")
            if args.debug and fdg_nodes:
                print(f"  {Colors.CYAN}│{Colors.RESET} 功能列表:")
                for n in fdg_nodes[:15]:
                    desc = n.get("function_description", "")[:60]
                    refs = len(n.get("action_refs", []))
                    print(f"  {Colors.CYAN}│{Colors.RESET}   [{n.get('index', '?')}] {desc}  ({refs} actions)")
                if len(fdg_nodes) > 15:
                    print(f"  {Colors.CYAN}│{Colors.RESET}   ... 共 {len(fdg_nodes)} 个功能节点")
        else:
            print(f"  {Colors.CYAN}│{Colors.RESET} FDG 文件:        {Colors.RED}未生成{Colors.RESET}")
        print(f"  {Colors.CYAN}└──────────────────────────────────────────┘{Colors.RESET}")

        phase_footer(phase2_success, phase2_elapsed,
                     f"功能节点数={len(fdg_nodes) if fdg_file.exists() else 0}")

        if not phase2_success:
            print(f"\n{Colors.RED}Phase 2 失败，终止后续阶段。{Colors.RESET}")
            sys.exit(1)

    # ═══════════════════════════════════════════════════════════
    # Phase 3: 数据依赖推断
    # ═══════════════════════════════════════════════════════════
    if args.phase in ("all", "fdg"):
        phase_header(3, 4, "数据依赖推断 (Data Dependency)")

        fixed_ptg = output_dir / "ptg.json"
        fdg_file = output_dir / "fdg.json"

        # ── 确认输入文件存在 ──────────────────────────────────
        if not fdg_file.exists():
            step_err(f"fdg.json 不存在 ({fdg_file}), 请先完成 Phase 2")
            sys.exit(1)

        # ── 输入 ──────────────────────────────────────────────
        fdg_data = json.loads(fdg_file.read_text(encoding="utf-8"))
        fdg_nodes = fdg_data.get("FDG", [])
        candidates = [n for n in fdg_nodes if n.get("data_in") or n.get("data_out")]
        print(f"  {Colors.CYAN}┌─ 输入 ─────────────────────────────────────┐{Colors.RESET}")
        print(f"  {Colors.CYAN}│{Colors.RESET} FDG 节点总数:    {len(fdg_nodes)}")
        print(f"  {Colors.CYAN}│{Colors.RESET} 候选节点:       {len(candidates)} (含 data_in/out)")
        print(f"  {Colors.CYAN}│{Colors.RESET} LLM 任务:       推断生产者→消费者依赖关系")
        print(f"  {Colors.CYAN}└──────────────────────────────────────────┘{Colors.RESET}")

        phase3_start = time.time()
        phase3_success = False
        try:
            step("LLM 推断数据依赖 (data_flow_prompt)...")
            explorer.build_FDG_with_dependency(str(fixed_ptg), str(fdg_file))

            # 处理硬编码路径问题: 将 token 文件从硬编码位置复制到输出目录
            hardcoded_token = Path("C:\\Users\\23314\\Desktop\\Fim\\output") / "LLM-Token-Stats.json"
            if hardcoded_token.exists():
                dest = output_dir / "LLM-Token-Stats.json"
                shutil.copy2(str(hardcoded_token), str(dest))
                step_warn(f"从硬编码路径恢复了 Token 统计: {hardcoded_token}")

            phase3_success = True
        except Exception as e:
            step_err(f"数据依赖推断异常: {e}")
            if args.debug:
                import traceback; traceback.print_exc()

        phase3_elapsed = time.time() - phase3_start
        phase3_total_deps = 0

        # ── 输出 ──────────────────────────────────────────────
        print(f"\n  {Colors.CYAN}┌─ 输出 ─────────────────────────────────────┐{Colors.RESET}")
        dep_file = output_dir / "fdg_with_data_dep.json"
        if dep_file.exists():
            dep_data = json.loads(dep_file.read_text(encoding="utf-8"))
            dep_nodes = dep_data.get("FDG", [])
            with_deps = [n for n in dep_nodes if n.get("data_dependencies")]
            phase3_total_deps = sum(len(n.get("data_dependencies", [])) for n in dep_nodes)
            print(f"  {Colors.CYAN}│{Colors.RESET} 文件:            {Colors.GREEN}fdg_with_data_dep.json{Colors.RESET}")
            print(f"  {Colors.CYAN}│{Colors.RESET} 有依赖的节点:   {len(with_deps)}")
            print(f"  {Colors.CYAN}│{Colors.RESET} 总依赖关系数:   {phase3_total_deps}")
            if args.debug and with_deps:
                print(f"  {Colors.CYAN}│{Colors.RESET} 依赖关系:")
                for n in with_deps[:10]:
                    idx = n.get("index", "?")
                    desc = n.get("function_description", "")[:50]
                    deps = n.get("data_dependencies", [])
                    print(f"  {Colors.CYAN}│{Colors.RESET}   [{idx}] {desc}")
                    print(f"  {Colors.CYAN}│{Colors.RESET}        depends on: {deps}")
        else:
            print(f"  {Colors.CYAN}│{Colors.RESET} 文件:            {Colors.RED}未生成{Colors.RESET}")
        print(f"  {Colors.CYAN}└──────────────────────────────────────────┘{Colors.RESET}")

        phase_footer(phase3_success, phase3_elapsed,
                     f"依赖关系数={phase3_total_deps}")

    # ═══════════════════════════════════════════════════════════
    # Phase 4: 测试生成
    # ═══════════════════════════════════════════════════════════
    if args.phase in ("all", "test"):
        phase_header(4, 4, "测试生成 (Task-level + App-level)")

        fdg_file = output_dir / "fdg.json"
        dep_file = output_dir / "fdg_with_data_dep.json"
        input_fdg = dep_file if dep_file.exists() else fdg_file

        # ── 确认输入文件存在 ──────────────────────────────────
        if not input_fdg.exists():
            step_err(f"FDG 文件不存在 ({input_fdg}), 请先完成 Phase 2 和 Phase 3")
            sys.exit(1)

        # ── 输入 ──────────────────────────────────────────────
        if dep_file.exists():
            dep_data = json.loads(dep_file.read_text(encoding="utf-8"))
            fdg_nodes = dep_data.get("FDG", [])
        else:
            fdg_data = json.loads(fdg_file.read_text(encoding="utf-8"))
            fdg_nodes = fdg_data.get("FDG", [])

        to_test = [n for n in fdg_nodes if n.get("to_test", False)]
        with_core = [n for n in fdg_nodes if n.get("core_logic")]
        with_deps = [n for n in fdg_nodes if n.get("data_dependencies")]

        print(f"  {Colors.CYAN}┌─ 输入 ─────────────────────────────────────┐{Colors.RESET}")
        print(f"  {Colors.CYAN}│{Colors.RESET} FDG 文件:         {input_fdg.name}")
        print(f"  {Colors.CYAN}│{Colors.RESET} to_test 节点:    {len(to_test)}")
        print(f"  {Colors.CYAN}│{Colors.RESET} 含 core_logic:   {len(with_core)} (Task-level 测试候选项)")
        print(f"  {Colors.CYAN}│{Colors.RESET} 含依赖关系:      {len(with_deps)} (App-level 测试候选项)")
        print(f"  {Colors.CYAN}└──────────────────────────────────────────┘{Colors.RESET}")

        print(f"\n  {Colors.YELLOW}⚠ 注意: 当前版本 task_level_test() 和 app_level_test(){Colors.RESET}")
        print(f"  {Colors.YELLOW}   中核心执行代码已被注释，仅生成测试计划 (LLM 调用)。{Colors.RESET}")
        print(f"  {Colors.YELLOW}   实际执行需取消 explorer.py 中相关代码的注释。{Colors.RESET}")

        phase4_start = time.time()
        phase4_success = False
        try:
            # 4a: Task-level
            step("4a. 运行 Task-level 测试生成...")
            explorer.read_PTG(str(output_dir / "ptg.json"))
            explorer.read_FDG(str(input_fdg))
            explorer.task_level_test()
            step_ok("Task-level 测试计划已生成")

            # 4b: App-level
            step("4b. 运行 App-level 测试生成...")
            explorer.app_level_test()
            step_ok("App-level 测试计划已生成")

            phase4_success = True
        except Exception as e:
            step_err(f"测试生成异常: {e}")
            if args.debug:
                import traceback; traceback.print_exc()

        phase4_elapsed = time.time() - phase4_start

        # ── 输出 ──────────────────────────────────────────────
        print(f"\n  {Colors.CYAN}┌─ 输出 ─────────────────────────────────────┐{Colors.RESET}")
        test_log = output_dir / "fdg_with_data_dep" / "test.log"
        if test_log.exists():
            log_size = test_log.stat().st_size
            print(f"  {Colors.CYAN}│{Colors.RESET} 测试日志: {Colors.GREEN}test.log{Colors.RESET} ({log_size/1024:.1f} KB)")
        else:
            print(f"  {Colors.CYAN}│{Colors.RESET} 测试日志: 测试计划已输出到 stdout (未写入文件)")
        print(f"  {Colors.CYAN}│{Colors.RESET} (测试计划详情请查看上方终端输出){Colors.RESET}")
        print(f"  {Colors.CYAN}└──────────────────────────────────────────┘{Colors.RESET}")

        phase_footer(phase4_success, phase4_elapsed, "")

    # ═══════════════════════════════════════════════════════════
    # Phase Final: 汇总报告
    # ═══════════════════════════════════════════════════════════
    total_elapsed = time.time() - global_start
    banner("测试完成 — 汇总报告")

    print(f"  {Colors.BOLD}总耗时: {timedelta(seconds=int(total_elapsed))}{Colors.RESET}")
    print(f"  结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # ── 产物清单 ──────────────────────────────────────────────
    print(f"  {Colors.BOLD}产物清单:{Colors.RESET}")

    print(f"  {Colors.CYAN}── PTG 相关 ──{Colors.RESET}")
    for pat in ["ptg_report_*.json", "ptg.json", "activity_coverage.json",
                "activity_coverage_history.jsonl"]:
        for f in sorted(output_dir.glob(pat)):
            file_info(str(f))

    print(f"  {Colors.CYAN}── FDG 相关 ──{Colors.RESET}")
    for pat in ["fdg.json", "fdg_with_data_dep.json"]:
        for f in sorted(output_dir.glob(pat)):
            file_info(str(f))

    print(f"  {Colors.CYAN}── Bug 记录 ──{Colors.RESET}")
    bug_files = sorted(output_dir.glob("bug*/bug.json"))
    if bug_files:
        print(f"  {Colors.GREEN}  ✓{Colors.RESET} 共检测到 {Colors.RED}{len(bug_files)} 个疑似 Bug{Colors.RESET}")
        for bf in bug_files:
            try:
                bd = json.loads(bf.read_text(encoding="utf-8"))
                btype = bd.get("bug_type", "unknown")
                bdesc = (bd.get("bug_description", "") or bd.get("bug_info", {}).get("bug_description", ""))[:80]
                print(f"      {bf.parent.name}: [{btype}] {bdesc}")
            except Exception:
                print(f"      {bf.parent.name}")
    else:
        print(f"  {Colors.DIM}  (未检测到 Bug){Colors.RESET}")

    print(f"  {Colors.CYAN}── 页面数据 ──{Colors.RESET}")
    pages_dirs = sorted(output_dir.glob("pages_*/"))
    if pages_dirs:
        latest = pages_dirs[-1]
        png_cnt = sum(1 for _ in latest.rglob("*.png"))
        json_cnt = sum(1 for _ in latest.rglob("*.json"))
        print(f"  {Colors.GREEN}  ✓{Colors.RESET} {latest.name}/ ({png_cnt} screenshots, {json_cnt} VHT files)")
    else:
        print(f"  {Colors.DIM}  (未生成页面数据){Colors.RESET}")

    print(f"  {Colors.CYAN}── LLM 消耗 ──{Colors.RESET}")
    token_files = list(output_dir.glob("**/LLM-Token-Stats.json"))
    if token_files:
        for tf in token_files:
            try:
                tok = json.loads(tf.read_text(encoding="utf-8")).get("token_stats", {})
                print(f"  {Colors.GREEN}  ✓{Colors.RESET} API 调用: {tok.get('calls', 0):,} 次")
                print(f"      Input tokens:  {tok.get('input_tokens', 0):,}")
                print(f"      Output tokens: {tok.get('output_tokens', 0):,}")
                print(f"      Total tokens:  {tok.get('total_tokens', 0):,}")
            except Exception:
                file_info(str(tf))

    print()

    # ── 关键指标摘要 ──────────────────────────────────────────
    print(f"  {Colors.BOLD}关键指标摘要:{Colors.RESET}")
    print()

    # Activity Coverage
    cov_file = output_dir / "activity_coverage.json"
    if cov_file.exists():
        cov = json.loads(cov_file.read_text(encoding="utf-8"))
        print(f"  📊 Activity 覆盖率:  {cov.get('activity_coverage', 0):.1%} "
              f"({cov.get('hit_count', 0)}/{cov.get('declared_count', 0)})")

    # FDG 功能点数
    fdg_file_check = output_dir / "fdg.json"
    if fdg_file_check.exists():
        fdg = json.loads(fdg_file_check.read_text(encoding="utf-8"))
        print(f"  🎯 识别功能点数:     {len(fdg.get('FDG', []))}")

    # 依赖关系数
    dep_file_check = output_dir / "fdg_with_data_dep.json"
    if dep_file_check.exists():
        dep = json.loads(dep_file_check.read_text(encoding="utf-8"))
        total_deps = sum(len(n.get("data_dependencies", [])) for n in dep.get("FDG", []))
        print(f"  🔗 数据依赖关系数:  {total_deps}")

    # Bug 数
    bug_cnt = len(bug_files)
    print(f"  🐛 检测到的 Bug:    {bug_cnt}")

    print()
    print(f"  {Colors.BOLD}{Colors.GREEN}所有阶段完成。输出目录: {output_dir}{Colors.RESET}")
    print()


if __name__ == "__main__":
    main()
