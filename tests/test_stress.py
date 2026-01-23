"""Stress test for YouTube subtitle rate limits.

This test makes repeated requests to YouTube to find the threshold
for rate limiting (429 errors).

Usage:
    uv run python tests/test_stress.py

NOTE: This will make actual network calls to YouTube and may trigger
rate limiting. Use with caution.
"""

import time
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.service import SubtitleExtractor


def stress_test_rate_limit(
    video_url: str = "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    max_requests: int = 50,
    delay_between_requests: float = 0,
):
    """
    Stress test YouTube subtitle extraction to find rate limit threshold.

    Args:
        video_url: YouTube video to test with
        max_requests: Maximum number of requests to make
        delay_between_requests: Seconds to wait between requests

    Returns:
        Dictionary with test results
    """
    extractor = SubtitleExtractor()

    results = {
        "success": 0,
        "failures": 0,
        "rate_limited": 0,
        "other_errors": 0,
        "first_429_at": None,
        "latencies": [],
        "error_messages": [],
    }

    print(f"{'=' * 60}")
    print(f"YouTube Subtitle Rate Limit Stress Test")
    print(f"{'=' * 60}")
    print(f"Video: {video_url}")
    print(f"Max requests: {max_requests}")
    print(f"Delay between requests: {delay_between_requests}s")
    print(f"{'=' * 60}\n")

    for i in range(1, max_requests + 1):
        start_time = time.time()

        try:
            video_id, subtitles = extractor.extract_subtitles(video_url, lang="en", output_format="json")

            latency = time.time() - start_time
            results["latencies"].append(latency)

            if subtitles and len(subtitles) > 0:
                results["success"] += 1
                status = "✅ SUCCESS"
            else:
                results["failures"] += 1
                status = "⚠️  EMPTY"

        except Exception as e:
            latency = time.time() - start_time
            error_msg = str(e)

            if "429" in error_msg or "rate limit" in error_msg.lower():
                results["rate_limited"] += 1
                status = "🚫 RATE LIMITED"
                if results["first_429_at"] is None:
                    results["first_429_at"] = i
                    print(f"\n{'!' * 60}")
                    print(f"FIRST RATE LIMIT DETECTED AT REQUEST #{i}")
                    print(f"{'!' * 60}\n")
            else:
                results["other_errors"] += 1
                status = "❌ ERROR"
                results["error_messages"].append(error_msg)

            results["latencies"].append(latency)

        # Print progress
        avg_latency = sum(results["latencies"][-5:]) / min(5, len(results["latencies"]))
        print(f"Request #{i:3d}: {status:20s} | Latency: {latency:5.2f}s | Avg(last 5): {avg_latency:5.2f}s | "
              f"Success: {results['success']} | 429s: {results['rate_limited']} | Errors: {results['other_errors']}")

        # If we've hit multiple 429s in a row, stop
        if results["rate_limited"] >= 3:
            print(f"\n{'=' * 60}")
            print(f"Multiple 429s detected. Stopping test.")
            print(f"{'=' * 60}\n")
            break

        # Sleep between requests if specified
        if delay_between_requests > 0 and i < max_requests:
            time.sleep(delay_between_requests)

    return results


def print_summary(results: dict, max_requests: int):
    """Print test summary."""
    total = results["success"] + results["failures"] + results["rate_limited"] + results["other_errors"]

    print(f"\n{'=' * 60}")
    print(f"SUMMARY")
    print(f"{'=' * 60}")
    print(f"Total requests made: {total}/{max_requests}")
    print(f"Successful:          {results['success']} ({100*results['success']/total:.1f}%)")
    print(f"Rate limited (429):   {results['rate_limited']} ({100*results['rate_limited']/total:.1f}%)")
    print(f"Empty responses:      {results['failures']} ({100*results['failures']/total:.1f}%)")
    print(f"Other errors:        {results['other_errors']} ({100*results['other_errors']/total:.1f}%)")

    if results["first_429_at"]:
        print(f"\n🚫 First 429 error at request: #{results['first_429_at']}")
        print(f"   Safe requests before rate limit: {results['first_429_at'] - 1}")
    else:
        print(f"\n✅ No rate limiting detected!")

    if results["latencies"]:
        avg_latency = sum(results["latencies"]) / len(results["latencies"])
        min_latency = min(results["latencies"])
        max_latency = max(results["latencies"])
        print(f"\nLatency stats:")
        print(f"   Average: {avg_latency:.2f}s")
        print(f"   Min:     {min_latency:.2f}s")
        print(f"   Max:     {max_latency:.2f}s")

    if results["error_messages"]:
        print(f"\nSample error messages:")
        for msg in results["error_messages"][:5]:
            print(f"   - {msg[:100]}")

    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    # Run stress test
    # You can adjust these parameters:
    MAX_REQUESTS = 200  # Increased to try to hit rate limits
    DELAY = 0  # seconds between requests (0 = as fast as possible)

    results = stress_test_rate_limit(
        video_url="https://www.youtube.com/watch?v=jNQXAC9IVRw",  # "Me at the zoo"
        max_requests=MAX_REQUESTS,
        delay_between_requests=DELAY,
    )

    print_summary(results, MAX_REQUESTS)
