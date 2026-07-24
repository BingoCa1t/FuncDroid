#!/bin/bash
# ============================================================
#  FuncDroid 完整环境搭建 & 验证脚本
#  适用于: Ubuntu 24.04 + 华为鸿蒙 4.2 真机 (ADB)
#  用法:   chmod +x setup_funcdroid.sh && ./setup_funcdroid.sh
# ============================================================

set -e

# -------------------- 颜色定义 --------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

PASS="${GREEN}[✓]${NC}"
FAIL="${RED}[✗]${NC}"
WARN="${YELLOW}[!]${NC}"
INFO="${CYAN}[→]${NC}"
STEP="${BLUE}${BOLD}[STEP]${NC}"

# 统计变量
TOTAL_STEPS=0
PASSED_STEPS=0
FAILED_STEPS=0
STEP_START_TIME=""

# 自动检测项目目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${FUNCDROID_PROJECT_DIR:-$SCRIPT_DIR}"
FUNCDROID_DIR="$PROJECT_DIR/funcdroid"

# -------------------- 工具函数 --------------------
step_begin() {
    TOTAL_STEPS=$((TOTAL_STEPS + 1))
    STEP_START_TIME=$(date +%s)
    echo ""
    echo -e "${STEP}=========================================================="
    echo -e "${STEP}  Step $TOTAL_STEPS: $1"
    echo -e "${STEP}=========================================================="
}

step_end() {
    local status=$1
    local msg="${2:-}"
    local elapsed=$(($(date +%s) - STEP_START_TIME))
    if [ "$status" -eq 0 ]; then
        PASSED_STEPS=$((PASSED_STEPS + 1))
        echo -e "${PASS} 完成 (${elapsed}s) ${msg}"
    else
        FAILED_STEPS=$((FAILED_STEPS + 1))
        echo -e "${FAIL} 失败 (${elapsed}s) ${msg}"
    fi
}

verify() {
    # 验证一条命令是否成功, 失败时输出提示
    local desc="$1"
    shift
    echo -n "    验证: $desc ... "
    if "$@" > /dev/null 2>&1; then
        echo -e "${GREEN}OK${NC}"
        return 0
    else
        echo -e "${RED}FAILED${NC}"
        return 1
    fi
}

check_cmd() {
    command -v "$1" > /dev/null 2>&1
}

fail_tip() {
    echo -e "${FAIL} ${RED}$1${NC}"
    if [ -n "$2" ]; then
        echo -e "    ${YELLOW}→ 建议: $2${NC}"
    fi
}

banner() {
    echo ""
    echo -e "${BLUE}${BOLD}"
    echo "  ╔══════════════════════════════════════════════════╗"
    echo "  ║     FuncDroid 环境搭建脚本 v1.0                    ║"
    echo "  ║     Ubuntu 24.04 + 华为鸿蒙 4.2 真机 (ADB)          ║"
    echo "  ╚══════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo "  项目目录: $PROJECT_DIR"
    echo "  开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
}

# -------------------- 开始 --------------------
banner

# ============================================================
# Step 1: 检查 Ubuntu 版本
# ============================================================
step_begin "检查操作系统版本"

echo "    当前系统信息:"
lsb_release -a 2>/dev/null || cat /etc/os-release
echo ""

UBUNTU_VERSION=$(lsb_release -rs 2>/dev/null || echo "0")
if [ "${UBUNTU_VERSION%%.*}" -ge 24 ]; then
    echo -e "${PASS} Ubuntu ${UBUNTU_VERSION} ≥ 24.04 ✓"
    step_end 0
else
    echo -e "${WARN} 当前版本 Ubuntu ${UBUNTU_VERSION}, 推荐使用 24.04"
    echo "    不同版本可能存在包名差异 (如 libgl1-mesa-glx → libgl1)"
    step_end 0 "版本不匹配但继续"
fi

# ============================================================
# Step 2: 安装系统依赖
# ============================================================
step_begin "安装系统依赖包"

PACKAGES=(
    wget curl git unzip zip
    openjdk-17-jdk openjdk-17-jre
    python3 python3-pip python3-venv
    libgl1 libglib2.0-0t64
    libsm6 libxext6 libxrender-dev libxcb1
    ffmpeg libxcb-xinerama0
)

# Ubuntu 24.04 将部分库重命名为 t64 版本 (64-bit time_t 迁移)
# 如果 t64 版本不存在, 回退到原始包名
GLIB_PKG="libglib2.0-0t64"
if ! apt-cache show "$GLIB_PKG" > /dev/null 2>&1; then
    GLIB_PKG="libglib2.0-0"
fi
# 将 PACKAGES 数组中的 libglib2.0-0t64 替换为实际可用的包名
for i in "${!PACKAGES[@]}"; do
    if [ "${PACKAGES[$i]}" = "libglib2.0-0t64" ]; then
        PACKAGES[$i]="$GLIB_PKG"
    fi
done

echo "    待安装: ${PACKAGES[*]}"
echo ""

sudo apt update -y

for pkg in "${PACKAGES[@]}"; do
    if dpkg -l "$pkg" 2>/dev/null | grep -q '^ii'; then
        echo -e "    ${GREEN}已安装${NC}  $pkg"
    else
        echo "    安装中...  $pkg"
        sudo apt install -y "$pkg" 2>&1 | tail -1
    fi
done

echo ""
ALL_OK=true
for pkg in "${PACKAGES[@]}"; do
    if ! dpkg -l "$pkg" 2>/dev/null | grep -q '^ii'; then
        echo -e "${FAIL} 未找到: $pkg"
        ALL_OK=false
    fi
done

if $ALL_OK; then
    echo -e "${PASS} 所有系统依赖已就绪"
    step_end 0
else
    echo -e "${WARN} 部分包安装失败, 请手动检查"
    step_end 1 "部分失败"
fi

# ============================================================
# Step 3: 验证 Java
# ============================================================
step_begin "验证 Java 环境"

if check_cmd java; then
    JAVA_VER=$(java -version 2>&1 | head -1)
    echo -e "${PASS} Java 已安装: $JAVA_VER"

    if java -version 2>&1 | grep -qE 'version "(1[7-9]|[2-9][0-9])'; then
        echo -e "${PASS} Java 版本 ≥ 17 ✓"
        step_end 0
    else
        echo -e "${WARN} Java 版本可能过旧, 推荐 17+"
        step_end 0 "版本较低但继续"
    fi
else
    fail_tip "Java 未安装" "sudo apt install -y openjdk-17-jdk"
    step_end 1
fi

# ============================================================
# Step 4: 安装/验证 ADB
# ============================================================
step_begin "安装 Android Platform-Tools (ADB)"

if check_cmd adb; then
    ADB_VER=$(adb version 2>&1 | head -1)
    echo -e "${PASS} ADB 已安装: $ADB_VER"
    step_end 0
else
    echo "    ADB 未安装, 正在下载..."
    ADB_DIR="$HOME/platform-tools"
    cd /tmp
    wget -q --show-progress https://dl.google.com/android/repository/platform-tools-latest-linux.zip
    rm -rf "$ADB_DIR"
    unzip -q platform-tools-latest-linux.zip -d "$HOME/"
    rm platform-tools-latest-linux.zip
    cd "$SCRIPT_DIR"

    # 添加到 PATH
    if ! grep -q "platform-tools" "$HOME/.bashrc"; then
        echo 'export PATH="$HOME/platform-tools:$PATH"' >> "$HOME/.bashrc"
    fi
    export PATH="$HOME/platform-tools:$PATH"

    if check_cmd adb; then
        echo -e "${PASS} ADB 安装成功: $(adb version 2>&1 | head -1)"
        step_end 0
    else
        fail_tip "ADB 安装失败" "手动下载: https://developer.android.com/studio/releases/platform-tools"
        step_end 1
    fi
fi

# ============================================================
# Step 5: 创建 Python 虚拟环境 (venv)
# ============================================================
step_begin "创建 Python venv 虚拟环境"

VENV_DIR="$PROJECT_DIR/venv"

# 检查 python3 是否可用
if ! check_cmd python3; then
    fail_tip "python3 未安装" "sudo apt install -y python3"
    step_end 1
    exit 1
fi

PY_VER=$(python3 --version 2>&1)
echo "    Python 版本: $PY_VER"

# 确保 venv 模块可用
if ! python3 -m venv --help > /dev/null 2>&1; then
    echo "    安装 python3-venv..."
    sudo apt install -y python3-venv
fi

# 删除旧 venv (如果存在且用户确认)
if [ -d "$VENV_DIR" ]; then
    echo -e "${WARN} 已存在虚拟环境: $VENV_DIR"
    read -p "    是否删除并重建? [Y/n] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]?$|^$ ]]; then
        rm -rf "$VENV_DIR"
        echo "    已删除旧环境"
    else
        echo "    保留旧环境"
    fi
fi

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo -e "${PASS} 虚拟环境已创建: $VENV_DIR"
else
    echo -e "${INFO} 使用已有虚拟环境"
fi

# 激活验证
source "$VENV_DIR/bin/activate"
if [ "$VIRTUAL_ENV" = "$VENV_DIR" ]; then
    echo -e "${PASS} 虚拟环境激活成功"
    echo "    Python: $(which python3)"
    echo "    Pip:    $(which pip)"
    step_end 0
else
    fail_tip "虚拟环境激活失败"
    step_end 1
fi

# ============================================================
# Step 6: 安装 Python 依赖
# ============================================================
step_begin "安装 Python 依赖包"

REQ_FILE="$PROJECT_DIR/requirements.txt"

if [ ! -f "$REQ_FILE" ]; then
    fail_tip "requirements.txt 未找到: $REQ_FILE"
    step_end 1
else
    echo "    升级 pip..."
    pip install --upgrade pip setuptools wheel --quiet

    echo "    从 requirements.txt 安装 (这一步可能较慢, 请耐心等待)..."
    echo ""

    FAILED_PKGS=""
    TOTAL_PKGS=$(grep -v '^$' "$REQ_FILE" | grep -v '^#' | wc -l)
    INSTALLED=0

    while IFS= read -r line; do
        # 跳过空行和注释
        [ -z "$line" ] && continue
        [[ "$line" =~ ^[[:space:]]*# ]] && continue

        pkg_name="${line%%==*}"
        echo -n "    [${INSTALLED}/${TOTAL_PKGS}] $pkg_name ... "

        if pip install "$line" --quiet 2>&1 | tail -1 > /dev/null; then
            echo -e "${GREEN}OK${NC}"
            INSTALLED=$((INSTALLED + 1))
        else
            echo -e "${RED}FAILED${NC}"
            FAILED_PKGS="$FAILED_PKGS $pkg_name"
        fi
    done < "$REQ_FILE"

    echo ""
    if [ -z "$FAILED_PKGS" ]; then
        echo -e "${PASS} 所有 $TOTAL_PKGS 个依赖安装成功"
        step_end 0
    else
        echo -e "${WARN} 以下包安装失败:$FAILED_PKGS"
        echo "    可以稍后手动安装: pip install$FAILED_PKGS"
        step_end 0 "部分失败但继续"
    fi
fi

# ============================================================
# Step 7: 验证关键 Python 包
# ============================================================
step_begin "验证关键 Python 包导入"

CRITICAL_PKGS=("uiautomator2" "openai" "cv2" "numpy" "androguard" "loguru" "dotenv")
ALL_IMPORT_OK=true

for mod in "${CRITICAL_PKGS[@]}"; do
    echo -n "    导入 $mod ... "
    case $mod in
        cv2) import_name="cv2" ;;
        dotenv) import_name="dotenv" ;;
        *) import_name="$mod" ;;
    esac
    if python3 -c "import $import_name" 2>/dev/null; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}FAILED${NC}"
        ALL_IMPORT_OK=false
    fi
done

if $ALL_IMPORT_OK; then
    echo -e "${PASS} 所有关键包导入成功"
    step_end 0
else
    fail_tip "部分包导入失败, 请检查 pip 安装"
    step_end 1
fi

# ============================================================
# Step 8: 修复代码兼容性问题
# ============================================================
step_begin "修复代码兼容性 (Linux / 包名 / 硬编码)"

FIXES_APPLIED=0

# 8.1 fix: hmbot 包名问题 — 创建符号链接
if [ ! -e "$PROJECT_DIR/hmbot" ]; then
    echo "    [修复1] 创建 hmbot → funcdroid 符号链接..."
    cd "$PROJECT_DIR"
    ln -sf funcdroid hmbot
    FIXES_APPLIED=$((FIXES_APPLIED + 1))
    echo -e "    ${PASS} 符号链接: hmbot → funcdroid"
else
    echo -e "    ${INFO} 符号链接已存在: hmbot → funcdroid"
fi

# 8.2 fix: findstr → grep (Linux 兼容)
EXPLORER_FILE="$FUNCDROID_DIR/explorer/explorer.py"
if [ -f "$EXPLORER_FILE" ]; then
    if grep -q 'findstr' "$EXPLORER_FILE" 2>/dev/null; then
        echo "    [修复2] findstr → grep (explorer.py:34)..."
        sed -i 's/| findstr mCurrentFocus/| grep mCurrentFocus/' "$EXPLORER_FILE"
        FIXES_APPLIED=$((FIXES_APPLIED + 1))
        echo -e "    ${PASS} findstr → grep 已修复"
    else
        echo -e "    ${INFO} findstr 问题不存在 (已修复或无此问题)"
    fi
else
    echo -e "    ${WARN} explorer.py 未找到, 跳过此修复"
fi

echo ""
echo -e "${PASS} 代码修复完成 (应用了 $FIXES_APPLIED 项修复)"
step_end 0

# ============================================================
# Step 9: 创建 .env 配置文件 (交互式)
# ============================================================
step_begin "配置 LLM API (.env 文件)"

ENV_FILE="$FUNCDROID_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    echo -e "${INFO} .env 文件已存在: $ENV_FILE"
    cat "$ENV_FILE" | sed 's/\(API_KEY=\).*/\1********/; s/\(SPECIALIZED_API_KEY=\).*/\1********/'
    read -p "    是否重新配置? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "    保留现有配置"
        step_end 0 "使用已有配置"
    fi
fi

# 重新配置
echo ""
echo "    请选择 LLM API 提供商:"
echo "    1) 豆包(火山引擎) + DeepSeek"
echo "    2) GPT-4o 中转代理"
echo "    3) 通义千问"
echo "    4) 自定义 (手动输入)"
read -p "    选择 [1-4]: " PROVIDER_CHOICE

case $PROVIDER_CHOICE in
    1)
        read -p "    豆包 API Key: " DOUBAO_KEY
        read -p "    DeepSeek API Key: " DS_KEY
        cat > "$ENV_FILE" << EOF
# 专用 LLM — 豆包 Vision (图像理解)
SPECIALIZED_BASE_URL="https://ark.cn-beijing.volces.com/api/v3/"
SPECIALIZED_MODEL="doubao-seed-1-6-vision-250815"
SPECIALIZED_API_KEY="$DOUBAO_KEY"

# 通用 LLM — DeepSeek (结构化推理)
BASE_URL="https://api.deepseek.com/v1/"
MODEL="deepseek-chat"
API_KEY="$DS_KEY"
EOF
        ;;
    2)
        read -p "    中转代理 URL (含 /v1): " PROXY_URL
        read -p "    API Key: " PROXY_KEY
        read -p "    模型名 (默认 gpt-4o): " PROXY_MODEL
        PROXY_MODEL="${PROXY_MODEL:-gpt-4o}"
        cat > "$ENV_FILE" << EOF
# 专用 LLM — GPT-4o 中转
SPECIALIZED_BASE_URL="$PROXY_URL"
SPECIALIZED_MODEL="$PROXY_MODEL"
SPECIALIZED_API_KEY="$PROXY_KEY"

# 通用 LLM — 同上
BASE_URL="$PROXY_URL"
MODEL="$PROXY_MODEL"
API_KEY="$PROXY_KEY"
EOF
        ;;
    3)
        read -p "    通义千问 API Key (DashScope): " QWEN_KEY
        cat > "$ENV_FILE" << EOF
# 专用 LLM — 通义千问 VL (视觉)
SPECIALIZED_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1/"
SPECIALIZED_MODEL="qwen-vl-max"
SPECIALIZED_API_KEY="$QWEN_KEY"

# 通用 LLM — 通义千问 Plus (文本)
BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1/"
MODEL="qwen-plus"
API_KEY="$QWEN_KEY"
EOF
        ;;
    4|*)
        read -p "    Specialized Base URL: " SURL
        read -p "    Specialized Model: " SMODEL
        read -p "    Specialized API Key: " SKEY
        read -p "    General Base URL: " GURL
        read -p "    General Model: " GMODEL
        read -p "    General API Key: " GKEY
        cat > "$ENV_FILE" << EOF
SPECIALIZED_BASE_URL="$SURL"
SPECIALIZED_MODEL="$SMODEL"
SPECIALIZED_API_KEY="$SKEY"
BASE_URL="$GURL"
MODEL="$GMODEL"
API_KEY="$GKEY"
EOF
        ;;
esac

echo -e "${PASS} .env 文件已创建: $ENV_FILE"
step_end 0

# ============================================================
# Step 10: 检查 llm.py 配置 (只提示, 不修改文件)
# ============================================================
step_begin "检查 llm.py 配置 (只读, 不会修改文件)"

LLM_FILE="$FUNCDROID_DIR/explorer/llm.py"

if [ ! -f "$LLM_FILE" ]; then
    fail_tip "llm.py 未找到: $LLM_FILE"
    step_end 1
else
    echo "    正在分析 llm.py 中的 API 配置..."
    echo ""

    python3 << PYCHECK
import re, os

llm_file = "$LLM_FILE"

with open(llm_file, 'r') as f:
    content = f.read()

issues = []

# 检查是否有 os.getenv 导入
if 'import os' not in content and 'from os' not in content:
    issues.append("缺少 import os — 需要在文件顶部添加: import os")

# 检查 client_llm 是否硬编码
if re.search(r'client_llm\s*=\s*OpenAI\(\s*\n\s*base_url\s*=\s*"[^"]*"', content):
    issues.append(
        "client_llm 使用了硬编码 base_url/api_key\\n"
        "    → 应改为从环境变量读取:\\n"
        '    client_llm = OpenAI(\\n'
        '        base_url=os.getenv("BASE_URL", "https://api.openai.com/v1/"),\\n'
        '        api_key=os.getenv("API_KEY", ""),\\n'
        '    )'
    )
elif 'os.getenv' in content and 'BASE_URL' in content:
    print("    [✓] client_llm 已从环境变量读取 ✓")
else:
    issues.append("client_llm 格式未识别, 请手动检查是否使用了环境变量")

# 检查 client_uitars 是否硬编码
if re.search(r'client_uitars\s*=\s*OpenAI\(\s*\n\s*base_url\s*=\s*"[^"]*"', content):
    issues.append(
        "client_uitars 使用了硬编码 base_url/api_key\\n"
        "    → 应改为从环境变量读取:\\n"
        '    client_uitars = OpenAI(\\n'
        '        base_url=os.getenv("SPECIALIZED_BASE_URL", "https://api.openai.com/v1/"),\\n'
        '        api_key=os.getenv("SPECIALIZED_API_KEY", ""),\\n'
        '    )'
    )
elif 'os.getenv' in content and 'SPECIALIZED_BASE_URL' in content:
    print("    [✓] client_uitars 已从环境变量读取 ✓")
else:
    issues.append("client_uitars 格式未识别, 请手动检查是否使用了环境变量")

# 检查是否有硬编码 API Key
hardcoded_keys = re.findall(r'(?:api_key|API_KEY)\s*=\s*"sk-[^"]{10,}"', content)
if hardcoded_keys:
    for key in hardcoded_keys:
        issues.append(f"发现硬编码 API Key: {key[:40]}... → 请替换为 os.getenv()")

print("")

if issues:
    print("  ╔════════════════════════════════════════════╗")
    print("  ║  llm.py 需要修改以下字段 (脚本不会自动修改):  ║")
    print("  ╚════════════════════════════════════════════╝")
    print("")
    for i, issue in enumerate(issues, 1):
        print(f"  [{i}] {issue}")
        print("")
    print(f"  文件路径: {llm_file}")
else:
    print("  [✓] llm.py 配置看起来已正确 (使用环境变量)")

PYCHECK

    echo ""
    echo -e "${INFO} 以上为检测结果, 请手动修改 llm.py 中的对应字段"
    step_end 0 "只读检查完成"
fi

# ============================================================
# Step 11: 连接手机 (ADB)
# ============================================================
step_begin "连接手机 (ADB)"

# 不重启 ADB 服务, 直接检测已连接设备

DEVICE_COUNT=$(adb devices 2>/dev/null | grep -c "device$" || echo 0)
echo "    检测到 $DEVICE_COUNT 台设备"

if [ "$DEVICE_COUNT" -eq 0 ]; then
    echo ""
    echo -e "${YELLOW}  ╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}  ║  未检测到 Android 设备                           ║${NC}"
    echo -e "${YELLOW}  ║                                                  ║${NC}"
    echo -e "${YELLOW}  ║  请确认:                                         ║${NC}"
    echo -e "${YELLOW}  ║  1. USB 数据线已连接 (非仅充电线)                  ║${NC}"
    echo -e "${YELLOW}  ║  2. 手机已开启 USB 调试                            ║${NC}"
    echo -e "${YELLOW}  ║  3. 手机弹窗已点击"允许"                           ║${NC}"
    echo -e "${YELLOW}  ║                                                  ║${NC}"
    echo -e "${YELLOW}  ║  连接成功后重新运行本脚本, 或手动执行:              ║${NC}"
    echo -e "${YELLOW}  ║    adb devices                                    ║${NC}"
    echo -e "${YELLOW}  ╚══════════════════════════════════════════════════╝${NC}"
    echo ""
    step_end 1 "未检测到设备"
    echo -e "${INFO} 你可以稍后重新运行本脚本, 或者手动完成后续步骤"
    exit 0
fi

DEVICE_SERIAL=$(adb devices | grep "device$" | head -1 | awk '{print $1}')
echo -e "${PASS} 设备已连接: $DEVICE_SERIAL"

# 获取设备信息
echo ""
echo "    设备详情:"
adb -s "$DEVICE_SERIAL" shell getprop ro.product.brand 2>/dev/null | xargs -I{} echo "      品牌: {}"
adb -s "$DEVICE_SERIAL" shell getprop ro.product.model 2>/dev/null | xargs -I{} echo "      型号: {}"
adb -s "$DEVICE_SERIAL" shell getprop ro.build.version.sdk 2>/dev/null | xargs -I{} echo "      SDK: {}"
adb -s "$DEVICE_SERIAL" shell getprop ro.build.version.release 2>/dev/null | xargs -I{} echo "      Android 版本: {}"

step_end 0

# ============================================================
# Step 12: 初始化 uiautomator2
# ============================================================
step_begin "初始化 uiautomator2"

echo "    在手机上安装 uiautomator2 测试 APK..."
echo "    (手机上可能会弹出安装确认，请留意手机屏幕)"
echo ""

python3 -m uiautomator2 init --serial "$DEVICE_SERIAL" 2>&1

echo ""
# 验证安装
if adb -s "$DEVICE_SERIAL" shell pm list packages 2>/dev/null | grep -q "com.github.uiautomator"; then
    echo -e "${PASS} uiautomator2 APK 已安装"
else
    echo -e "${WARN} uiautomator2 APK 可能未正确安装"
fi

# 测试 uiautomator2 连接
echo -n "    测试 uiautomator2 连接 ... "
CONNECT_TEST=$(python3 -c "
import uiautomator2 as u2
try:
    d = u2.connect('$DEVICE_SERIAL')
    info = d.info
    print(f'OK|{info.get(\"displayWidth\")}x{info.get(\"displayHeight\")}')
except Exception as e:
    print(f'FAIL|{e}')
" 2>&1)

if [[ "$CONNECT_TEST" == OK* ]]; then
    echo -e "${GREEN}成功${NC}"
    echo "    屏幕分辨率: ${CONNECT_TEST#OK|}"
    step_end 0
else
    echo -e "${RED}失败${NC}"
    echo "    错误: ${CONNECT_TEST#FAIL|}"
    echo -e "${WARN} 请检查手机上的 uiautomator2 是否被系统拦截"
    step_end 1
fi

# ============================================================
# Step 13: 运行设备验证脚本
# ============================================================
step_begin "运行完整设备验证"

VERIFY_OUTPUT=$(python3 << PYEOF
import sys, cv2, uiautomator2 as u2

serial = "$DEVICE_SERIAL"
errors = []

# 1. 连接
try:
    d = u2.connect(serial)
except Exception as e:
    print(f"FAIL|连接失败: {e}")
    sys.exit(1)

# 2. 设备信息
info = d.info
print(f"OK|品牌={info.get('brand','?')} 型号={info.get('productName','?')} SDK={info.get('sdkInt','?')}")

# 3. 截图
try:
    img = d.screenshot(format='opencv')
    h, w = img.shape[:2]
    print(f"OK|截图成功 {w}x{h}")
except Exception as e:
    print(f"FAIL|截图失败: {e}")

# 4. UI 树
try:
    xml = d.dump_hierarchy()
    xml_str = xml if isinstance(xml, str) else xml.decode()
    print(f"OK|UI树获取成功 len={len(xml_str)}")
except Exception as e:
    print(f"FAIL|UI树失败: {e}")

# 5. 按键
try:
    d.press("back")
    import time; time.sleep(1)
    print("OK|按键测试通过")
except Exception as e:
    print(f"FAIL|按键失败: {e}")

print("DONE")
PYEOF
)

echo ""
PASS_COUNT=0
FAIL_COUNT=0
while IFS= read -r line; do
    if [[ "$line" == OK* ]]; then
        echo -e "    ${PASS} ${line#OK|}"
        PASS_COUNT=$((PASS_COUNT + 1))
    elif [[ "$line" == FAIL* ]]; then
        echo -e "    ${FAIL} ${line#FAIL|}"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    elif [[ "$line" == "DONE" ]]; then
        break
    fi
done <<< "$VERIFY_OUTPUT"

echo ""
echo "    通过: $PASS_COUNT | 失败: $FAIL_COUNT"

if [ "$FAIL_COUNT" -eq 0 ]; then
    echo -e "${PASS} 设备验证全部通过！"
    step_end 0
else
    echo -e "${WARN} 部分验证失败, 请根据以上错误排查"
    step_end 0 "部分失败"
fi

# ============================================================
# Step 14: 最终汇总
# ============================================================
echo ""
echo -e "${BLUE}${BOLD}"
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║              搭建完成 - 汇总报告                    ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo -e "${NC}"
echo "  总步骤: $TOTAL_STEPS  |  通过: ${GREEN}$PASSED_STEPS${NC}  |  失败: ${RED}$FAILED_STEPS${NC}"
echo "  结束时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
echo "  环境摘要:"
echo "    Ubuntu:     $(lsb_release -rs 2>/dev/null || echo '?')"
echo "    Java:       $(java -version 2>&1 | head -1 | cut -d' ' -f3 | tr -d '"')"
echo "    Python:     $(python3 --version 2>&1)"
echo "    ADB:        $(adb version 2>&1 | head -1)"
echo "    虚拟环境:     $VENV_DIR"
echo "    设备序列号:   $DEVICE_SERIAL"
echo "    .env 文件:   $ENV_FILE"
echo ""
echo -e "${GREEN}${BOLD}  🎉 环境搭建完成!${NC}"
echo ""
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║  下一步 — 运行你的第一个 FuncDroid 测试:          ║"
echo "  ║                                                  ║"
echo "  ║  ./run_funcdroid.sh your_app.apk ./output 3600   ║"
echo "  ╚══════════════════════════════════════════════════╝"
