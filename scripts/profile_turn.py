"""Profile one chat/stream turn — event timestamps and LLM step timing."""
import json
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
USER = sys.argv[2] if len(sys.argv) > 2 else "user_096"
MSG = sys.argv[3] if len(sys.argv) > 3 else "没预约能核销吗"

edge = {
    "user_id": USER,
    "focus_order_id": "order_096" if USER == "user_096" else None,
    "city": "北京",
    "recent_order_ids": ["order_096"] if USER == "user_096" else [],
    "local_voucher_summary": [],
    "behavior_tags": [],
    "location_permission": True,
    "packet_size_bytes": 100,
}

req = urllib.request.Request(
    f"{BASE}/api/v1/chat/sessions",
    data=json.dumps(edge).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    sid = json.loads(resp.read())["session_id"]

body = {"session_id": sid, "message": MSG, "stream": True, "edge_context": edge}
req2 = urllib.request.Request(
    f"{BASE}/api/v1/chat/stream",
    data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)

t0 = time.perf_counter()
first_thinking = None
first_token = None
thinking_tokens = 0
reply_tokens = 0
events: list[tuple[float, str, dict]] = []

with urllib.request.urlopen(req2, timeout=180) as resp:
    raw = resp.read().decode("utf-8", errors="replace")

for frame in raw.replace("\r\n", "\n").split("\n\n"):
    ev, data = "message", ""
    for line in frame.split("\n"):
        if line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:"):
            data += line[5:].strip()
    if not data:
        continue
    now_ms = (time.perf_counter() - t0) * 1000
    try:
        p = json.loads(data)
    except json.JSONDecodeError:
        p = {}
    events.append((now_ms, ev, p))
    if ev in ("thinking", "thinking_token") and first_thinking is None:
        first_thinking = now_ms
    if ev == "thinking_token":
        thinking_tokens += 1
    if ev == "token":
        reply_tokens += 1
        if first_token is None:
            first_token = now_ms

print(f"user={USER} message={MSG!r}")
print(f"total_ms={round((time.perf_counter() - t0) * 1000)}")
print(f"first_thinking_ms={round(first_thinking) if first_thinking else None}")
print(f"first_token_ms={round(first_token) if first_token else None}")
print(f"thinking_token_count={thinking_tokens} reply_token_count={reply_tokens}")
print("--- timeline ---")
for now_ms, ev, p in events:
    if ev == "pipeline":
        steps = (p.get("pipeline") or {}).get("steps") or []
        if not steps:
            continue
        last = steps[-1]
        print(f"{now_ms:7.0f}ms pipeline +{last.get('name')} | {str(last.get('detail', ''))[:95]}")
    elif ev == "gather_step":
        step = p.get("step") or {}
        phase = p.get("phase") or "gather"
        step_ms = p.get("step_ms")
        pf = " prefetch" if p.get("prefetch") else ""
        print(
            f"{now_ms:7.0f}ms {phase} #{step.get('step')} {step.get('action')}{pf} "
            f"step_ms={step_ms}"
        )
    elif ev == "done":
        model = (p.get("pipeline") or {}).get("model") or {}
        print(f"{now_ms:7.0f}ms done latency_s={model.get('latency_s')}")
