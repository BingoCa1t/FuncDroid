#!/bin/bash
# FuncDroid 一键运行脚本 (华为鸿蒙真机适配版)
# 用法:
#   ./run_funcdroid.sh <APK_PATH> [OUTPUT_DIR] [TIMEOUT_SECONDS]
# 示例:
#   ./run_funcdroid.sh ./myapp.apk ./output 1800
#
# 前置条件:
#   1. 手机通过 ADB 连接 (adb devices 能看到设备)
#   2. uiautomator2 已初始化 (python3 -m uiautomator2 init)
#   3. funcdroid/.env 文件已配置 (SPECIALIZED_BASE_URL, API_KEY 等)

set -e

# ===== 配置 =====
APK_PATH="${1:?请提供 APK 路径}"
OUTPUT_DIR="${2:-./output}"
TIMEOUT="${3:-3600}"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo "  FuncDroid Automated Testing Pipeline"
echo "  适配: 华为鸿蒙 4.2 真机 (ADB)"
echo "=========================================="
echo "APK: $APK_PATH"
echo "Output: $OUTPUT_DIR"
echo "Timeout: ${TIMEOUT}s (${TIMEOUT}秒 = $((TIMEOUT/60)) 分钟)"
echo "Project: $PROJECT_DIR"
echo "=========================================="

# ----- 检查 ADB 环境 -----
if ! command -v adb &> /dev/null; then
    echo "[ERROR] adb not found in PATH. 请先安装 Android Platform-Tools"
    exit 1
fi

DEVICE_COUNT=$(adb devices | grep -c "device$" || true)
if [ "$DEVICE_COUNT" -eq 0 ]; then
    echo "[ERROR] 没有检测到设备!"
    echo "请检查:"
    echo "  1. USB 数据线是否正确连接"
    echo "  2. 手机是否开启了 'USB调试'"
    echo "  3. 手机弹窗是否点击了'允许'"
    echo ""
    echo "尝试修复:"
    echo "  adb kill-server && adb start-server && adb devices"
    exit 1
fi

DEVICE_SERIAL=$(adb devices | grep "device$" | head -1 | awk '{print $1}')
echo "[INFO] 检测到设备: $DEVICE_SERIAL"

# ----- 检查 .env 文件 -----
ENV_FILE="$PROJECT_DIR/funcdroid/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "[WARN] .env 文件未找到: $ENV_FILE"
    echo "[WARN] 请确保 LLM API 配置正确，否则运行时会报错"
fi

# ----- 激活虚拟环境 -----
cd "$PROJECT_DIR"
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    echo "[INFO] Python 虚拟环境已激活"
else
    echo "[WARN] 未找到虚拟环境，使用系统 Python"
fi

# ----- 创建输出目录 -----
mkdir -p "$OUTPUT_DIR"
ABSOLUTE_OUTPUT=$(realpath "$OUTPUT_DIR")

# ----- 运行测试 -----
echo "[INFO] 开始 FuncDroid 测试..."
echo "[INFO] 开始时间: $(date '+%Y-%m-%d %H:%M:%S')"

# 通过环境变量传参，避免路径含空格/特殊字符导致 Python 解析错误
export FUNCDROID_PROJECT_DIR="$PROJECT_DIR"
export FUNCDROID_APK_PATH="$APK_PATH"
export FUNCDROID_DEVICE_SERIAL="$DEVICE_SERIAL"
export FUNCDROID_TIMEOUT="$TIMEOUT"
export FUNCDROID_OUTPUT_DIR="$ABSOLUTE_OUTPUT"

set +e  # 暂时关闭 set -e，以便捕获 Python 退出码
python3 -c "
import sys, os, time

PROJECT_DIR = os.environ['FUNCDROID_PROJECT_DIR']
sys.path.insert(0, PROJECT_DIR)

from hmbot.device.device import Device
from hmbot.utils.proto import OperatingSystem
from hmbot.utils.utils import get_android_available_devices
from hmbot.app.android_app import AndroidApp
from hmbot.explorer.explorer import Explorer
from hmbot.explorer.utils import grant_all_permissions

# 获取设备
devices = get_android_available_devices()
device_serial = devices[0] if devices else os.environ['FUNCDROID_DEVICE_SERIAL']
print(f'[INFO] 使用设备: {device_serial}')

# 初始化设备
device = Device(device_serial, OperatingSystem.ANDROID)

# 解析 APK
apk_path = os.environ['FUNCDROID_APK_PATH'].replace(chr(92), '/')
print(f'[INFO] 解析 APK: {apk_path}')
app = AndroidApp(app_path=apk_path)
print(f'[INFO] 应用名: {app.app_name}')
print(f'[INFO] 包名: {app.package_name}')
print(f'[INFO] 入口 Activity: {app.entry_ability}')
print(f'[INFO] 声明的 Activities 数量: {len(app.abilities)}')

# 卸载旧版本 (如果有)
print('[INFO] 清理旧版本...')
try:
    device.uninstall_app(app)
    time.sleep(2)
except Exception:
    pass  # 首次安装，无需卸载

# 安装 APK
print('[INFO] 安装 APK...')
device.install_app(app)
time.sleep(5)

# 授予所有权限
print('[INFO] 授予运行时权限...')
grant_all_permissions(app.package_name)

# 启动应用
print('[INFO] 启动应用...')
device.start_app(app)
time.sleep(10)

# 创建 Explorer
explorer = Explorer(
    device=device,
    app_name=app.app_name,
    app=app
)
explorer.time_limit_seconds = int(os.environ['FUNCDROID_TIMEOUT'])

# 开始完整测试流程
# full_explorer 包含:
#   1) PTG 探索 (页面转换图构建)
#   2) FDG 构建 (功能流程图)
#   3) 数据依赖分析
#   4) 功能级测试 (task_level_test)
#   5) 跨功能测试 (app_level_test)
output_dir = os.environ['FUNCDROID_OUTPUT_DIR']
print(f'[INFO] 开始完整测试流程 (超时: {os.environ[\"FUNCDROID_TIMEOUT\"]}s)...')
explorer.full_explorer(output_dir=output_dir)

elapsed = time.time() - explorer.start_time
print(f'[INFO] 测试完成! 总耗时: {elapsed:.0f}s ({elapsed/60:.1f} 分钟)')
print(f'[INFO] 结果目录: {output_dir}')
"
EXIT_CODE=$?
set -e  # 恢复 set -e

echo ""
echo "=========================================="
echo "  测试结束"
echo "  结束时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "  退出码: $EXIT_CODE"
echo "=========================================="

# ----- 输出结果摘要 -----
if [ -f "$OUTPUT_DIR/activity_coverage.json" ]; then
    echo ""
    echo "=== Activity Coverage 摘要 ==="
    python3 -c "
import json
with open('$OUTPUT_DIR/activity_coverage.json') as f:
    data = json.load(f)
    print(f\"  Declared: {data.get('declared_count', 'N/A')}\")
    print(f\"  Visited:  {data.get('visited_count', 'N/A')}\")
    print(f\"  Coverage: {data.get('activity_coverage', 'N/A')}\")
"
fi

if [ -f "$OUTPUT_DIR/LLM-Token-Stats.json" ]; then
    echo ""
    echo "=== LLM Token 消耗 ==="
    python3 -c "
import json
with open('$OUTPUT_DIR/LLM-Token-Stats.json') as f:
    data = json.load(f)
    ts = data.get('token_stats', {})
    print(f\"  API 调用次数: {ts.get('calls', 'N/A')}\")
    print(f\"  总 Tokens:    {ts.get('total_tokens', 'N/A')}\")
"
fi

# 统计 Bug
BUG_COUNT=$(find "$OUTPUT_DIR" -name "bug.json" 2>/dev/null | wc -l)
echo ""
echo "=== Bug 统计 ==="
echo "  检测到的 Bug 记录数: $BUG_COUNT"

exit $EXIT_CODE