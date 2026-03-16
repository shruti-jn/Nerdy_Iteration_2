"""
API Provider Validation & Latency Measurement.
Pipeline stage: Infrastructure — validates all external service API keys and measures baseline latency.
This script makes REAL API calls. Requires valid API keys in .env.
Run: python -m benchmarks.validate_providers
"""

import asyncio
import json
import os
import struct
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

# Add parent dir to path for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import settings


@dataclass
class ValidationResult:
    """Result of a single provider validation."""
    provider: str
    model: str
    metric: str
    target: str
    measured: str
    status: str  # "PASS" or "FAIL"


def generate_test_audio(duration_s: float = 1.0, sample_rate: int = 16000) -> bytes:
    """Generate a short near-silent audio clip in WAV format for STT testing.

    Returns a valid WAV file (RIFF header + PCM16 data) so that the Deepgram
    prerecorded API can determine the encoding and sample rate from the header
    rather than requiring them as separate parameters.
    """
    import random
    num_samples = int(sample_rate * duration_s)
    random.seed(42)
    samples = [random.randint(-10, 10) for _ in range(num_samples)]
    pcm_data = struct.pack(f"<{num_samples}h", *samples)

    # Build a minimal RIFF/WAV header (44 bytes)
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(pcm_data)
    file_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", file_size, b"WAVE",
        b"fmt ", 16, 1, num_channels, sample_rate,
        byte_rate, block_align, bits_per_sample,
        b"data", data_size,
    )
    return header + pcm_data


async def validate_deepgram(results: list[ValidationResult], num_runs: int = 5):
    """Validate Deepgram STT (Nova-3) and measure prerecorded transcription latency.

    Uses the v6 SDK ``listen.v1.media.transcribe_file`` API (no PrerecordedOptions
    class — options are passed as keyword arguments directly).
    """
    print("\n--- DEEPGRAM (STT) ---")
    try:
        from deepgram import DeepgramClient

        client = DeepgramClient(api_key=settings.deepgram_api_key)
        audio_data = generate_test_audio(1.0)

        latencies = []
        for i in range(num_runs):
            start = time.perf_counter()
            # WAV header carries encoding/sample-rate info — no need to specify them
            response = client.listen.v1.media.transcribe_file(
                request=audio_data,
                model="nova-3",
                language="en",
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies.append(elapsed_ms)

            transcript = ""
            try:
                ch = response.results.channels
                if ch and ch[0].alternatives:
                    transcript = ch[0].alternatives[0].transcript or ""
            except Exception:
                pass
            print(f"  Run {i+1}: Deepgram Nova-3: {elapsed_ms:.0f}ms, transcript: '{transcript}'")

        avg = sum(latencies) / len(latencies)
        status = "PASS" if avg < 300 else "FAIL"
        print(f"  Average: {avg:.0f}ms — {status}")
        results.append(ValidationResult("Deepgram", "nova-3", "STT latency", "<300ms", f"{avg:.0f}ms", status))

    except Exception as e:
        print(f"  ERROR: {e}")
        results.append(ValidationResult("Deepgram", "nova-3", "STT latency", "<300ms", f"ERROR: {e}", "FAIL"))


async def validate_groq(results: list[ValidationResult], num_runs: int = 5):
    """Validate Groq LLM and measure TTFT for both models."""
    print("\n--- GROQ (LLM) ---")

    models = [
        ("llama-3.3-70b-versatile", 400),
        ("llama-3.1-8b-instant", 200),
    ]

    for model_name, max_ms in models:
        try:
            from groq import Groq

            client = Groq(api_key=settings.groq_api_key)
            latencies = []

            for i in range(num_runs):
                start = time.perf_counter()
                stream = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": "You are a helpful Socratic tutor."},
                        {"role": "user", "content": "What is photosynthesis?"},
                    ],
                    stream=True,
                    max_tokens=100,
                )

                ttft = None
                for chunk in stream:
                    content = chunk.choices[0].delta.content
                    if content and ttft is None:
                        ttft = (time.perf_counter() - start) * 1000
                        break

                if ttft:
                    latencies.append(ttft)
                    print(f"  Run {i+1}: Groq {model_name} TTFT: {ttft:.0f}ms")

            if latencies:
                avg = sum(latencies) / len(latencies)
                status = "PASS" if avg < max_ms else "FAIL"
                print(f"  Average: {avg:.0f}ms — {status}")
                results.append(ValidationResult("Groq", model_name, "TTFT", f"<{max_ms}ms", f"{avg:.0f}ms", status))
            else:
                results.append(ValidationResult("Groq", model_name, "TTFT", f"<{max_ms}ms", "No data", "FAIL"))

        except Exception as e:
            print(f"  ERROR ({model_name}): {e}")
            results.append(ValidationResult("Groq", model_name, "TTFT", f"<{max_ms}ms", f"ERROR: {e}", "FAIL"))


async def validate_cartesia(results: list[ValidationResult], num_runs: int = 5):
    """Validate Cartesia TTS (Sonic-3) and measure time-to-first-audio.

    Uses AsyncCartesia + generate_sse (SSE streaming) — the same path as the
    production CartesiaTTSAdapter — so TTFA reflects real first-audio latency
    rather than total synthesis time.
    """
    print("\n--- CARTESIA (TTS) ---")
    try:
        from cartesia import AsyncCartesia

        voice_id = getattr(settings, "cartesia_voice_id", "a0e99841-438c-4a64-b679-ae501e7d6091")
        latencies = []

        for i in range(num_runs):
            client = AsyncCartesia(api_key=settings.cartesia_api_key)
            start = time.perf_counter()
            ttfa = None
            try:
                stream = await client.tts.generate_sse(
                    model_id="sonic-3",
                    transcript="What do you think about that?",
                    voice={"mode": "id", "id": voice_id},
                    output_format={
                        "container": "raw",
                        "encoding": "pcm_s16le",
                        "sample_rate": 16000,
                    },
                )
                async for event in stream:
                    if event.type == "chunk" and event.audio:
                        ttfa = (time.perf_counter() - start) * 1000
                        break
            finally:
                await client.close()
            if ttfa is None:
                ttfa = (time.perf_counter() - start) * 1000
            latencies.append(ttfa)
            print(f"  Run {i+1}: Cartesia Sonic TTFA: {ttfa:.0f}ms")

        avg = sum(latencies) / len(latencies)
        # 600ms ceiling: Cartesia cold SSE TTFA includes HTTP + model startup overhead.
        # The production pipeline budget (tts_max_ms=300ms) is measured in the full
        # pipeline benchmark where the target is 700ms. 600ms gives a reasonable
        # provider-level gate with a buffer above the observed ~480ms baseline.
        status = "PASS" if avg < 600 else "FAIL"
        print(f"  Average: {avg:.0f}ms — {status}")
        results.append(ValidationResult("Cartesia", "sonic-3", "TTFA", "<600ms", f"{avg:.0f}ms", status))

    except Exception as e:
        print(f"  ERROR: {e}")
        results.append(ValidationResult("Cartesia", "sonic-3", "TTFA", "<600ms", f"ERROR: {e}", "FAIL"))


async def validate_simli(results: list[ValidationResult]):
    """Validate Simli API key using the /faces endpoint (current API)."""
    print("\n--- SIMLI (Avatar) ---")
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.simli.ai/faces",
                headers={"x-simli-api-key": settings.simli_api_key},
                timeout=10.0,
            )
            valid = response.status_code == 200
            face_count = len(response.json()) if valid else 0
            status = "PASS" if valid else "FAIL"
            print(f"  Simli API key valid: {valid}, available faces: {face_count}")
            results.append(ValidationResult("Simli", "-", "API valid", "True", str(valid), status))

    except Exception as e:
        print(f"  ERROR: {e}")
        results.append(ValidationResult("Simli", "-", "API valid", "True", f"ERROR: {e}", "FAIL"))


async def validate_logfire(results: list[ValidationResult]):
    """Validate Logfire configuration."""
    print("\n--- LOGFIRE ---")
    try:
        import logfire

        logfire.configure()
        with logfire.span("validation.test_span", attributes={"test": True}):
            pass
        print("  Logfire configured: True")
        results.append(ValidationResult("Logfire", "-", "Configured", "True", "True", "PASS"))

    except Exception as e:
        print(f"  ERROR: {e}")
        results.append(ValidationResult("Logfire", "-", "Configured", "True", f"ERROR: {e}", "FAIL"))


async def validate_braintrust(results: list[ValidationResult]):
    """Validate Braintrust connection using synchronous login().

    init_logger() is lazy — it defers auth until the first flush, which means
    it would incorrectly return PASS and then emit noisy tracebacks in the
    background. braintrust.login(api_key=...) performs an eager, synchronous
    credential check that raises immediately on failure.
    """
    print("\n--- BRAINTRUST ---")
    api_key = settings.braintrust_api_key
    if not api_key:
        print("  Braintrust API key not set (BRAINTRUST_API_KEY missing)")
        results.append(ValidationResult("Braintrust", "-", "Connected", "True", "False (no key)", "FAIL"))
        return
    try:
        import braintrust

        braintrust.login(api_key=api_key, force_login=True)
        print("  Braintrust login: True")
        results.append(ValidationResult("Braintrust", "-", "Connected", "True", "True", "PASS"))

    except Exception as e:
        print(f"  ERROR: {e}")
        results.append(ValidationResult("Braintrust", "-", "Connected", "True", f"ERROR: {e}", "FAIL"))


async def validate_aiortc(results: list[ValidationResult]):
    """Validate aiortc peer connection initialization."""
    print("\n--- AIORTC ---")
    try:
        from aiortc import RTCPeerConnection

        pc = RTCPeerConnection()
        await pc.close()
        print("  aiortc peer connection: True")
        results.append(ValidationResult("aiortc", "-", "PeerConn", "True", "True", "PASS"))

    except Exception as e:
        print(f"  ERROR: {e}")
        results.append(ValidationResult("aiortc", "-", "PeerConn", "True", f"ERROR: {e}", "FAIL"))


def print_summary_table(results: list[ValidationResult]):
    """Print a formatted summary table of all validation results."""
    print("\n" + "=" * 80)
    print("PROVIDER VALIDATION SUMMARY")
    print("=" * 80)
    header = f"{'Provider':<12} {'Model':<25} {'Metric':<15} {'Target':<10} {'Measured':<15} {'Status'}"
    print(header)
    print("-" * 80)
    for r in results:
        status_icon = "PASS" if r.status == "PASS" else "FAIL"
        print(f"{r.provider:<12} {r.model:<25} {r.metric:<15} {r.target:<10} {r.measured:<15} {status_icon}")
    print("-" * 80)

    passed = sum(1 for r in results if r.status == "PASS")
    total = len(results)
    print(f"\nResult: {passed}/{total} passed")


def save_results(results: list[ValidationResult], output_path: str):
    """Save validation results to JSON."""
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": [asdict(r) for r in results],
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.status == "PASS"),
            "failed": sum(1 for r in results if r.status == "FAIL"),
        },
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nResults saved to {output_path}")


async def main():
    """Run all provider validations."""
    print("Live AI Video Tutor — Provider Validation")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")

    results: list[ValidationResult] = []

    # Run validations (some can be parallel, but sequential is safer for rate limits)
    await validate_deepgram(results)
    await validate_groq(results)
    await validate_cartesia(results)
    await validate_simli(results)
    await validate_logfire(results)
    await validate_braintrust(results)
    await validate_aiortc(results)

    print_summary_table(results)

    output_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "results",
        "provider_validation.json",
    )
    save_results(results, output_path)


if __name__ == "__main__":
    asyncio.run(main())
