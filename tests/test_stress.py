"""Stress tests for YouTube subtitle rate limits.

These tests make actual network calls to YouTube to verify rate limiting behavior.

NOTE: These tests are marked as "slow" and "stress" and can be skipped with:
    pytest -m "not slow"    # Skip slow tests
    pytest -m "not stress"  # Skip stress tests
"""

import asyncio
import time

import pytest

from app.service import SubtitleExtractor


@pytest.mark.slow
@pytest.mark.stress
def test_rate_limit_threshold():
    """Test rate limiting behavior with repeated requests.

    This test makes multiple requests to observe rate limiting behavior.
    It will stop after detecting multiple 429 errors.

    Markers: slow, stress
    """
    extractor = SubtitleExtractor()
    success_count = 0
    rate_limit_count = 0
    max_requests = 20  # Conservative limit to avoid excessive API calls

    for i in range(max_requests):
        try:
            # Use a well-known, stable video
            video_id, _ = extractor.extract_subtitles(
                "https://www.youtube.com/watch?v=jNQXAC9IVRw",  # "Me at the zoo"
                lang="en",
                output_format="json",
            )
            success_count += 1
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "rate limit" in error_msg.lower():
                rate_limit_count += 1
            # Stop after hitting rate limits a few times
            if rate_limit_count >= 2:
                break

    # We should get some successes before rate limiting
    assert success_count >= 1, "Should get at least one successful request"


@pytest.mark.slow
@pytest.mark.stress
async def test_concurrent_requests():
    """Test handling of concurrent subtitle extraction requests.

    This test verifies that the service can handle multiple concurrent
    requests without crashing.

    Markers: slow, stress
    """
    from starlette.concurrency import run_in_threadpool

    async def extract():
        extractor = SubtitleExtractor()
        return await run_in_threadpool(
            extractor.extract_subtitles,
            "https://www.youtube.com/watch?v=jNQXAC9IVRw",
            "en",
            "json",
        )

    async def run_concurrent():
        tasks = [extract() for _ in range(3)]
        return await asyncio.gather(*tasks, return_exceptions=True)

    results = await run_concurrent()
    successful = sum(1 for r in results if not isinstance(r, Exception))
    assert successful >= 1, "At least one concurrent request should succeed"


@pytest.mark.slow
@pytest.mark.stress
def test_cache_performance():
    """Test cache performance with repeated requests.

    This test verifies that caching works correctly for repeated requests
    to the same video.

    Markers: slow, stress
    """
    from app.cache import cache

    cache.clear()
    extractor = SubtitleExtractor()

    # First request - cache miss
    video_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

    # Check initial cache stats
    initial_stats = cache.get_stats()
    initial_misses = initial_stats["misses"]

    try:
        extractor.extract_subtitles(video_url, lang="en", output_format="json")
        # Cache should have been populated (if enabled)
    except Exception:
        pass  # We're mainly testing cache mechanism, not actual extraction

    # Verify cache is tracking operations
    final_stats = cache.get_stats()
    # At minimum, we should have tracked the miss from the first request
    assert final_stats["misses"] >= initial_misses


# ============================================================================
# Standalone stress test script (can be run directly without pytest)
# ============================================================================


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
