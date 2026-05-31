#!/usr/bin/env python3
"""
Weixin-safe message sender with automatic chunking.

Usage (from cron pre-check script):
  python3 ~/.hermes/scripts/weixin_chunked_send.py "message text"

Or import as module:
  from weixin_chunked_send import chunk_message
"""

import os, sys, json, subprocess, re

WEIXIN_MAX_LEN = 2000   # Safe margin for Weixin message length

def chunk_message(text: str, max_len: int = WEIXIN_MAX_LEN) -> list:
    """Split long text into Weixin-safe chunks.
    
    Strategy:
    - Split by newline first to preserve readability
    - If single line exceeds max_len, split by char blocks
    - Never silently truncate content
    """
    if len(text) <= max_len:
        return [text]
    
    chunks = []
    current = ''
    
    for line in text.split('\n'):
        if len(line) > max_len:
            # Flush current chunk
            if current:
                chunks.append(current)
                current = ''
            # Split extremely long line by character blocks
            for i in range(0, len(line), max_len - 20):
                chunks.append(line[i:i + max_len - 20] + '...(续)')
            continue
        
        if len(current) + len(line) + 1 > max_len:
            chunks.append(current)
            current = line
        else:
            current = (current + '\n' + line) if current else line
    
    if current:
        chunks.append(current)
    
    return chunks


def send_via_hermes_cli(message: str) -> bool:
    """Send message via hermes send_message tool (for cron pre-check context).
    
    In cron pre-check context, we can't use the send_message tool directly.
    Instead, we output the chunks to stdout and let the cron system handle delivery.
    
    Actually, the best approach for cron is to save chunks to a temp file
    and the cron runner reads it. But for now, we'll print chunks with markers.
    """
    chunks = chunk_message(message)
    
    if len(chunks) == 1:
        print(message)
        return True
    
    # Multi-chunk: add chunk indicator
    for i, chunk in enumerate(chunks, 1):
        marker = f"\n═══ 报告分段 {i}/{len(chunks)} ═══\n"
        print(marker + chunk)
    
    return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 weixin_chunked_send.py <message>")
        sys.exit(1)
    
    message = sys.argv[1]
    
    # If message is a file path (starts with @), read from file
    if message.startswith('@'):
        filepath = message[1:]
        with open(filepath) as f:
            message = f.read()
    
    # If message is "read_from_stdin", read from stdin
    if message == 'read_from_stdin':
        message = sys.stdin.read()
    
    chunks = chunk_message(message)
    print(f"[weixin_chunked_send] chunks={len(chunks)}, total_len={len(message)}")
    
    for i, chunk in enumerate(chunks, 1):
        print(f"\n[CHUNK {i}/{len(chunks)}]")
        print(chunk)
