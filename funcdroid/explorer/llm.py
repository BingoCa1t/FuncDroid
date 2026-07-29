from dotenv import load_dotenv
import os
import time
from openai import OpenAI, APIStatusError, APITimeoutError, APIConnectionError
from threading import Lock
from typing import Any, Dict

# ---- configurable retry settings ----
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
LLM_RETRY_BACKOFF_BASE = float(os.getenv("LLM_RETRY_BACKOFF_BASE", "2.0"))

TOKEN_LOCK = Lock()
LLM_LOCK = Lock()  # serialise all LLM API calls — the backend does not support concurrency

TOKEN_STATS: Dict[str, int] = {
    "calls": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0,
}

TOKEN_LOGS = []  # list[dict]

# 模块级标志：API 是否支持 thinking 参数
# 设置环境变量 LLM_DISABLE_THINKING=true 可全局关闭
# 若不设置，首次调用时自动检测，不支持则自动跳过
_THINKING_SUPPORTED = os.getenv("LLM_DISABLE_THINKING", "").lower() not in ("1", "true", "yes")

def _extract_usage(resp: Any) -> Dict[str, int]:
    """
    Try to extract usage tokens from OpenAI Responses API compatible object.
    Return dict with keys: input_tokens, output_tokens, total_tokens
    """
    usage = getattr(resp, "usage", None)
    if usage is None and isinstance(resp, dict):
        usage = resp.get("usage")

    # OpenAI Responses API: usage.{input_tokens, output_tokens, total_tokens}
    it = getattr(usage, "input_tokens", None) if usage is not None else None
    ot = getattr(usage, "output_tokens", None) if usage is not None else None
    tt = getattr(usage, "total_tokens", None) if usage is not None else None

    # dict fallback
    if usage is not None and isinstance(usage, dict):
        it = usage.get("input_tokens", it)
        ot = usage.get("output_tokens", ot)
        tt = usage.get("total_tokens", tt)

    # Some gateways may use prompt/completion naming
    if it is None and usage is not None:
        it = getattr(usage, "prompt_tokens", None)
    if ot is None and usage is not None:
        ot = getattr(usage, "completion_tokens", None)
    if tt is None and usage is not None:
        tt = getattr(usage, "total_tokens", None)

    # ensure int
    it = int(it) if it is not None else 0
    ot = int(ot) if ot is not None else 0
    tt = int(tt) if tt is not None else (it + ot)

    return {"input_tokens": it, "output_tokens": ot, "total_tokens": tt}

def _add_usage(resp: Any, tag: str = "", model: str = "") -> Dict[str, int]:
    """
    Update global TOKEN_STATS and (optional) TOKEN_LOGS.
    Return this-call usage dict.
    """
    u = _extract_usage(resp)

    with TOKEN_LOCK:
        TOKEN_STATS["calls"] += 1
        TOKEN_STATS["input_tokens"] += u["input_tokens"]
        TOKEN_STATS["output_tokens"] += u["output_tokens"]
        TOKEN_STATS["total_tokens"] += u["total_tokens"]

        # 可选：记录每次调用明细
        TOKEN_LOGS.append({
            "tag": tag,
            "model": model,
            "input_tokens": u["input_tokens"],
            "output_tokens": u["output_tokens"],
            "total_tokens": u["total_tokens"],
        })
        # 可选：限制长度，避免跑太久内存涨
        if len(TOKEN_LOGS) > 2000:
            del TOKEN_LOGS[:1000]

    return u


load_dotenv()


client_llm = OpenAI(
    base_url=os.getenv("BASE_URL", "https://api.openai.com/v1"),
    api_key=os.getenv("API_KEY", "dummy"),
)

client_uitars = OpenAI(
    base_url=os.getenv("SPECIALIZED_BASE_URL"),
    api_key=os.getenv("SPECIALIZED_API_KEY"),
    timeout=120.0,     # 120s per-request timeout — avoids hanging forever
    max_retries=0,      # we handle retries ourselves with backoff
)

# def ask_llm(content):
#     resp = client_llm.responses.create(
#         model="gpt-4o",
#         input=[{
#             "role": "user",
#             "content": content
#         }],
#         temperature=0,
#     )
#     return resp.output_text


def _call_llm_with_retry(tag: str, fn):
    """
    Call fn() with LLM_LOCK serialisation and automatic retry on transient errors.
    fn() should return the OpenAI response object.
    """
    global _THINKING_SUPPORTED
    last_exc = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            with LLM_LOCK:
                resp = fn()
            _add_usage(resp, tag=tag, model=os.getenv("SPECIALIZED_MODEL") or "")
            return resp.output_text
        except (APIStatusError, APITimeoutError, APIConnectionError) as e:
            last_exc = e
            status = getattr(e, 'status_code', None)

            # 自动检测 API 是否不支持 'thinking' 参数，若不支持则全局禁用并重试
            if status == 400 and _THINKING_SUPPORTED:
                err_text = str(e)
                # e.body 可能是 dict 或 str，统一转为字符串检测
                if hasattr(e, 'body'):
                    err_text += str(e.body)
                if 'thinking' in err_text:
                    _THINKING_SUPPORTED = False
                    print(f"[LLM:{tag}] API does not support 'thinking' param, retrying without it ...")
                    continue  # fn() 闭包内会读取 _THINKING_SUPPORTED 决定是否传 extra_body

            retryable = status in (429, 502, 503, 504) if status else True
            if not retryable and status is not None and status < 500:
                raise  # 4xx (non-429) = client error, don't retry
            if attempt == LLM_MAX_RETRIES:
                raise
            delay = max(LLM_RETRY_BACKOFF_BASE ** attempt, 2.0)
            if status == 502:
                delay = max(delay, 60.0)  # Cloudflare asks for >= 60s
            elif status is None:
                # timeout / connection error — server already struggled for 120s,
                # give it real time to recover before retrying
                delay = max(delay, 30.0)
            print(f"[LLM:{tag}] attempt {attempt}/{LLM_MAX_RETRIES} failed ({type(e).__name__}"
                  f"{f' status={status}' if status else ''}), retrying in {delay:.0f}s ...")
            time.sleep(delay)

    raise last_exc  # type: ignore


def _extra_body():
    """返回 extra_body，若 API 不支持 thinking 参数则返回 None"""
    return {"thinking": {"type": "disabled"}} if _THINKING_SUPPORTED else None


def ask_llm(content):
    def _call():
        return client_uitars.responses.create(
            model=os.getenv("SPECIALIZED_MODEL"),
            input=[{"role": "user", "content": content}],
            temperature=0,
            extra_body=_extra_body(),
        )
    return _call_llm_with_retry("ask_llm", _call)


def ask_uitars(content):
    def _call():
        return client_uitars.responses.create(
            model=os.getenv("SPECIALIZED_MODEL"),
            input=[{"role": "user", "content": content}],
            temperature=0,
            extra_body=_extra_body(),
        )
    return _call_llm_with_retry("ask_uitars", _call)


def ask_uitars_without_thinking(content):
    def _call():
        return client_uitars.responses.create(
            model=os.getenv("SPECIALIZED_MODEL"),
            input=[{"role": "user", "content": content}],
            temperature=0,
            extra_body=_extra_body(),
        )
    return _call_llm_with_retry("ask_uitars_without_thinking", _call)


def ask_uitars_messages(messages):
    def _call():
        return client_uitars.responses.create(
            model=os.getenv("SPECIALIZED_MODEL"),
            input=messages,
            temperature=0,
            extra_body=_extra_body(),
        )
    return _call_llm_with_retry("ask_uitars_messages", _call)




    


