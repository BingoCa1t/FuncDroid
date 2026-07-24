"""验证手机连接和 uiautomator2 是否正常工作"""
import uiautomator2 as u2
import cv2
import sys

# 获取设备列表
import subprocess
r = subprocess.check_output(["adb", "devices"]).decode()
lines = [l for l in r.splitlines() if l.strip().endswith("device")]
if not lines:
    print("[FAIL] 没有检测到设备，请检查 USB 连接和 USB 调试开关")
    sys.exit(1)

serial = lines[0].split()[0]
print(f"[OK] 设备已连接: {serial}")

# 连接 uiautomator2
try:
    d = u2.connect(serial)
    info = d.info
    print(f"[OK] uiautomator2 连接成功")
    print(f"     型号: {info.get('productName', 'N/A')}")
    print(f"     品牌: {info.get('brand', 'N/A')}")
    print(f"     SDK: {info.get('sdkInt', 'N/A')}")
    print(f"     分辨率: {info.get('displayWidth', '?')}x{info.get('displayHeight', '?')}")
except Exception as e:
    print(f"[FAIL] uiautomator2 连接失败: {e}")
    print("       请执行: python3 -m uiautomator2 init")
    sys.exit(1)

# 测试截图
try:
    img = d.screenshot(format='opencv')
    h, w = img.shape[:2]
    print(f"[OK] 截图成功, 尺寸: {w}x{h}")
    cv2.imwrite("screenshot_test.png", img)
    print(f"[OK] 测试截图已保存: screenshot_test.png")
except Exception as e:
    print(f"[FAIL] 截图失败: {e}")
    sys.exit(1)

# 测试 UI 树
try:
    xml = d.dump_hierarchy()
    xml_str = xml if isinstance(xml, str) else xml.decode()
    print(f"[OK] UI 树获取成功, 长度: {len(xml_str)} 字符")
except Exception as e:
    print(f"[FAIL] UI 树获取失败: {e}")
    sys.exit(1)

# 测试简单点击和返回
try:
    d.press("back")
    print("[OK] 按键操作成功 (Back)")
except Exception as e:
    print(f"[FAIL] 按键操作失败: {e}")
    sys.exit(1)

print("\n===== 全部验证通过！手机已准备好运行 FuncDroid =====")
