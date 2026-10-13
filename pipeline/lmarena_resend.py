#!/usr/bin/env python3
"""LMArena agent 输入框重发：execCommand 插入 + InputEvent 触发 React 状态 + 点发送。
解决 React 受控 contenteditable 不识别 execCommand 插入、Send 按钮保持 disabled 的问题。
用法：python3 lmarena_resend.py --prompt-file xxx.txt
"""
import argparse
import base64
import sys
import time

sys.path.insert(0, "/home/hatch/data/perpetua")
from lmarena_agent import js, ab  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt-file", required=True)
    a = ap.parse_args()
    prompt = open(a.prompt_file, encoding="utf-8").read().strip()
    b64 = base64.b64encode(prompt.encode("utf-8")).decode("ascii")

    expr = (
        "(function(){var bin=atob('" + b64 + "');"
        "var bytes=Uint8Array.from(bin,function(c){return c.charCodeAt(0)});"
        "var t=new TextDecoder().decode(bytes);"
        "var el=document.querySelector('[contenteditable]');"
        "if(!el)return 'NO_EDITOR';el.focus();"
        "document.execCommand('selectAll',false,null);"
        "document.execCommand('insertText',false,t);"
        "el.dispatchEvent(new InputEvent('input',{bubbles:true,data:t}));"
        "var btns=[...document.querySelectorAll('button')];"
        "var send=btns.find(b=>(b.getAttribute('aria-label')||b.innerText||'')"
        ".toLowerCase().includes('send'));"
        "if(!send)return 'NO_SEND_BTN len='+el.innerText.length;"
        "if(send.disabled)return 'STILL_DISABLED len='+el.innerText.length;"
        "send.click();return 'CLICKED len='+el.innerText.length;})()"
    )
    print("result:", js(expr, timeout=60), flush=True)

    # 等 URL 跳到新会话
    for _ in range(24):
        time.sleep(5)
        try:
            href = js("(function(){return location.href})()")
        except RuntimeError:
            href = ""
        print("url:", href, flush=True)
        if href and "/agent/" in href and not href.rstrip("/").endswith("/agent"):
            print("NEW_SESSION:", href, flush=True)
            return 0
    print("TIMEOUT: 未跳转到新会话", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
