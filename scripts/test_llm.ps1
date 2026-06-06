# Test LLM connectivity (Doubao / OpenAI-compatible)
$ErrorActionPreference = "Stop"
$root = Join-Path $PSScriptRoot ".."
$python = Join-Path $root "apps\api\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

Push-Location (Join-Path $root "apps\api")
& $python -c @"
import asyncio, json
from app.services.llm import LLMService
from app.config import settings

async def main():
    svc = LLMService()
    ping = await svc.ping()
    print(json.dumps({
        'mode': svc.mode,
        'model': settings.llm_model,
        'base_url': settings.llm_base_url,
        'temperature': settings.llm_temperature,
        'max_tokens': settings.llm_max_tokens,
        'ping': ping,
    }, ensure_ascii=False, indent=2))

asyncio.run(main())
"@
Pop-Location
