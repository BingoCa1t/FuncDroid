import base64
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
import os
from openai import OpenAI, APIStatusError

load_dotenv(os.path.join(os.path.dirname(__file__), "funcdroid", ".env"))


# ── 工具函数 ─────────────────────────────────────────────

def _make_client(name="default"):
    """创建 OpenAI client"""
    return OpenAI(
        base_url=os.getenv("SPECIALIZED_BASE_URL", "https://api.chatanywhere.tech/v1"),
        api_key=os.getenv("SPECIALIZED_API_KEY", "dummy"),
    )


def _dummy_image_b64():
    """生成一张 1x1 白色 JPEG 的 base64（用于测试多模态）"""
    # 使用 PIL 生成有效的最小 JPEG
    try:
        from PIL import Image
        import io, base64
        img = Image.new("RGB", (1, 1), color=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        # 无 PIL 时用最小有效 BMP 转 base64（BMP 格式简单，可手动构造）
        # 1x1 白色 BMP (54 bytes header + 4 bytes pixel data)
        import struct, base64
        bmp = b'BM' + struct.pack('<I', 58) + b'\x00\x00\x00\x00' + struct.pack('<I', 54)
        bmp += struct.pack('<I', 40) + struct.pack('<I', 1) + struct.pack('<I', 1)
        bmp += struct.pack('<H', 1) + struct.pack('<H', 24) + b'\x00' * 24
        bmp += b'\xff\xff\xff\x00'
        # 转为 JPEG 不可行，直接用 BMP 的 base64 但声明为 JPEG，代理可能拒绝
        # 实际使用时建议安装 PIL
        return base64.b64encode(bmp).decode()


# ── 测试 1: Chat Completions API (messages + type: "text") ──

def test_chat_text(client):
    """Chat API — 纯文本"""
    resp = client.chat.completions.create(
        model=os.getenv("SPECIALIZED_MODEL", "gpt-4o"),
        messages=[{"role": "user", "content": "Reply with just OK"}],
        max_tokens=10,
    )
    return f"[OK] Chat-text: {resp.choices[0].message.content}"


def test_chat_text_array(client):
    """Chat API — content 为数组 [type: text]"""
    resp = client.chat.completions.create(
        model=os.getenv("SPECIALIZED_MODEL", "gpt-4o"),
        messages=[{"role": "user", "content": [{"type": "text", "text": "Reply OK"}]}],
        max_tokens=10,
    )
    return f"[OK] Chat-text-array: {resp.choices[0].message.content}"


def test_chat_vision(client):
    """Chat API — 多模态 (text + image_url)"""
    resp = client.chat.completions.create(
        model=os.getenv("SPECIALIZED_MODEL", "gpt-4o"),
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image in one word."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_dummy_image_b64()}"}},
            ],
        }],
        max_tokens=20,
    )
    return f"[OK] Chat-vision: {resp.choices[0].message.content}"


# ── 测试 2: Responses API (input + type: "input_text") ──

def test_responses_text(client):
    """Responses API — 纯文本（llm.py 当前使用的方式）"""
    resp = client.responses.create(
        model=os.getenv("SPECIALIZED_MODEL", "gpt-4o"),
        input=[{"role": "user", "content": "Reply with just OK"}],
        temperature=0,
    )
    return f"[OK] Responses-text: {resp.output_text}"


def test_responses_input_text(client):
    """Responses API — content 数组含 input_text（== llm.py ask_llm 实际格式）"""
    resp = client.responses.create(
        model=os.getenv("SPECIALIZED_MODEL", "gpt-4o"),
        input=[{
            "role": "user",
            "content": [{"type": "input_text", "text": "Reply OK"}],
        }],
        temperature=0,
    )
    return f"[OK] Responses-input_text: {resp.output_text}"


def test_responses_vision(client):
    """Responses API — input_text + input_image（== llm.py 多模态实际格式）"""
    resp = client.responses.create(
        model=os.getenv("SPECIALIZED_MODEL", "gpt-4o"),
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Describe this image in one word."},
                {"type": "input_image", "image_url": f"data:image/jpeg;base64,{_dummy_image_b64()}"},
            ],
        }],
        temperature=0,
    )
    return f"[OK] Responses-vision: {resp.output_text}"


def test_responses_with_thinking_disabled(client):
    """Responses API — 带 extra_body thinking disabled（== llm.py 完整调用格式）"""
    resp = client.responses.create(
        model=os.getenv("SPECIALIZED_MODEL", "gpt-4o"),
        input=[{"role": "user", "content": "Reply with just OK"}],
        temperature=0,
        extra_body={"thinking": {"type": "disabled"}},
    )
    return f"[OK] Responses-thinking-off: {resp.output_text}"


# ── 测试 3: API 格式对比 ──

def test_api_format_comparison(client):
    """对比 Chat API 和 Responses API 的可用性，定位报错点"""
    results = []

    # 3.1 Chat API — text
    try:
        r = test_chat_text(client)
        results.append(("✅ Chat-text", r, None))
    except Exception as e:
        results.append(("❌ Chat-text", str(e)[:120], e))

    # 3.2 Chat API — text array
    try:
        r = test_chat_text_array(client)
        results.append(("✅ Chat-text-array", r, None))
    except Exception as e:
        results.append(("❌ Chat-text-array", str(e)[:120], e))

    # 3.3 Chat API — vision
    try:
        r = test_chat_vision(client)
        results.append(("✅ Chat-vision", r, None))
    except Exception as e:
        results.append(("❌ Chat-vision", str(e)[:120], e))

    # 3.4 Responses API — 纯文本
    try:
        r = test_responses_text(client)
        results.append(("✅ Responses-text", r, None))
    except Exception as e:
        results.append(("❌ Responses-text", str(e)[:120], e))

    # 3.5 Responses API — input_text
    try:
        r = test_responses_input_text(client)
        results.append(("✅ Responses-input_text", r, None))
    except Exception as e:
        results.append(("❌ Responses-input_text", str(e)[:120], e))

    # 3.6 Responses API — vision
    try:
        r = test_responses_vision(client)
        results.append(("✅ Responses-vision", r, None))
    except Exception as e:
        results.append(("❌ Responses-vision", str(e)[:120], e))

    # 3.7 Responses API — thinking disabled
    try:
        r = test_responses_with_thinking_disabled(client)
        results.append(("✅ Responses-thinking-off", r, None))
    except Exception as e:
        results.append(("❌ Responses-thinking-off", str(e)[:120], e))

    return results


# ── 测试 4: 第二轮对话（模拟 _test_function 多轮历史） ──

def test_round2_assistant_with_input_text(client):
    """
    模拟 explorer.py _test_function 第二轮调用的对话历史：
      input[0]: user + input_text  (任务指令)
      input[1]: user + input_image (首屏截图)
      input[2]: assistant + input_text ← 💥 这里会报错
    """
    history = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "You are a mobile GUI testing agent. Your task: tap the 'Settings' button. Reply with a JSON action."}
            ]
        },
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Current page screenshot:"},
                {"type": "input_image", "image_url": f"data:image/jpeg;base64,{_dummy_image_b64()}"}
            ]
        },
        {
            "role": "assistant",
            "content": [
                {"type": "input_text", "text": 'Thought: I should tap Settings.\nAction: click(point=\'<point>500 300</point>\')\nDescription: Tap Settings.'}
            ]
        },
    ]
    resp = client.responses.create(
        model=os.getenv("SPECIALIZED_MODEL", "gpt-4o"),
        input=history,
        temperature=0,
    )
    return f"[OK] Round2-input_text: {resp.output_text[:80]}"


def test_round2_assistant_with_output_text(client):
    """
    同上，但 assistant 消息用 output_text（修复后的正确格式）。
    """
    history = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "You are a mobile GUI testing agent. Your task: tap the 'Settings' button. Reply with a JSON action."}
            ]
        },
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Current page screenshot:"},
                {"type": "input_image", "image_url": f"data:image/jpeg;base64,{_dummy_image_b64()}"}
            ]
        },
        {
            "role": "assistant",
            "content": [
                {"type": "output_text", "text": 'Thought: I should tap Settings.\nAction: click(point=\'<point>500 300</point>\')\nDescription: Tap Settings.'}
            ]
        },
    ]
    resp = client.responses.create(
        model=os.getenv("SPECIALIZED_MODEL", "gpt-4o"),
        input=history,
        temperature=0,
    )
    return f"[OK] Round2-output_text: {resp.output_text[:80]}"


def test_round2_chat_api_equivalent(client):
    """
    相同场景用 Chat Completions API（assistant 消息统一用 type: "text"）。
    """
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "You are a mobile GUI testing agent. Your task: tap the 'Settings' button. Reply with a JSON action."}
            ]
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Current page screenshot:"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_dummy_image_b64()}"}}
            ]
        },
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": 'Thought: I should tap Settings.\nAction: click(point=\'<point>500 300</point>\')\nDescription: Tap Settings.'}
            ]
        },
    ]
    resp = client.chat.completions.create(
        model=os.getenv("SPECIALIZED_MODEL", "gpt-4o"),
        messages=messages,
        temperature=0,
        max_tokens=100,
    )
    return f"[OK] Round2-Chat: {resp.choices[0].message.content[:80]}"


def test_round2_comparison(client):
    """第二轮对话格式对比 —— 定位 explorer.py 真实报错"""
    results = []

    # A: assistant + input_text（== explorer.py 当前写法，预期报错）
    try:
        r = test_round2_assistant_with_input_text(client)
        results.append(("✅ Round2-assistant+input_text", r, None))
    except Exception as e:
        results.append(("❌ Round2-assistant+input_text", str(e)[:150], e))

    # B: assistant + output_text（修复方案）
    try:
        r = test_round2_assistant_with_output_text(client)
        results.append(("✅ Round2-assistant+output_text", r, None))
    except Exception as e:
        results.append(("❌ Round2-assistant+output_text", str(e)[:150], e))

    # C: Chat API 等效（备选方案）
    try:
        r = test_round2_chat_api_equivalent(client)
        results.append(("✅ Round2-Chat-API", r, None))
    except Exception as e:
        results.append(("❌ Round2-Chat-API", str(e)[:150], e))

    return results


# ── 主入口 ────────────────────────────────────────────────

if __name__ == "__main__":
    client = _make_client()
    print(f"API Base: {os.getenv('SPECIALIZED_BASE_URL')}")
    print(f"Model:    {os.getenv('SPECIALIZED_MODEL', 'gpt-4o')}\n")

    # ── 阶段 1: 基础格式测试 ──
    print("=" * 60)
    print("阶段 1: 基础格式测试（Chat API vs Responses API）")
    print("=" * 60)
    results = test_api_format_comparison(client)
    for label, detail, _err in results:
        print(f"  {label}: {detail}")

    chat_ok = sum(1 for l, _, _ in results if "Chat" in l and "✅" in l)
    responses_ok = sum(1 for l, _, _ in results if "Responses" in l and "✅" in l)
    print(f"\n  基础: Chat {chat_ok}/3  |  Responses {responses_ok}/4\n")

    # ── 阶段 2: 第二轮对话测试（模拟 _test_function 真实场景） ──
    print("=" * 60)
    print("阶段 2: 第二轮对话（模拟 explorer._test_function 多轮历史）")
    print("=" * 60)
    r2 = test_round2_comparison(client)
    for label, detail, _err in r2:
        print(f"  {label}: {detail}")

    r2_ok = sum(1 for l, _, _ in r2 if "✅" in l)
    print(f"\n  第二轮对话通过: {r2_ok}/{len(r2)}\n")

    # ── 总结 ──
    print("─" * 60)
    print("总结:")
    if r2_ok == 3:
        print("  所有格式均可用")
    else:
        input_text_failed = any("input_text" in l and "❌" in l for l, _, _ in r2)
        output_text_ok = any("output_text" in l and "✅" in l for l, _, _ in r2)
        chat_ok_r2 = any("Chat" in l and "✅" in l for l, _, _ in r2)
        if input_text_failed and output_text_ok:
            print("  根因确认: assistant 消息不能用 input_text，需改为 output_text")
            print("  修复: explorer.py 中所有 role=assistant 的 input_text → output_text")
        if chat_ok_r2:
            print("  备选: 切换到 Chat Completions API（assistant 用 type: text）")
