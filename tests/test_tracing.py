import threading

import pytest

from src.orchestrator.tracing import TraceAggregator


def test_trace_aggregation_accepts_bounded_events_once():
    aggregator = TraceAggregator(max_bytes=256, max_events=5)
    events = [
        {"step": "start", "duration_ms": 1},
        {"step": "finish", "duration_ms": 2},
    ]

    first = aggregator.aggregate("run-1", "transition-1", events)
    retry = aggregator.aggregate(
        "run-1",
        "transition-1",
        [{"step": "different"}],
    )

    assert first["status"] == "accepted"
    assert first["event_count"] == 2
    assert retry == first
    assert aggregator.get_trace("transition-1") == events
    assert [record["decision"] for record in aggregator.audit_records] == [
        "terminal",
        "idempotent",
    ]


def test_trace_aggregation_rejects_before_retaining_oversized_payload():
    aggregator = TraceAggregator(max_bytes=64, max_events=10)

    outcome = aggregator.aggregate(
        "run-private",
        "transition-private",
        [{"span": "small"}, {"payload": "private-value" * 20}],
    )

    assert outcome["status"] == "rejected"
    assert outcome["reason"] == "trace_memory_limit"
    assert aggregator.get_trace("transition-private") is None
    assert aggregator.get_outcome("transition-private") == outcome
    assert "private-value" not in repr(aggregator.audit_records)


def test_trace_aggregation_rejects_event_count_limit_without_stale_trace():
    aggregator = TraceAggregator(max_bytes=1024, max_events=2)

    outcome = aggregator.aggregate(
        "run-1",
        "transition-1",
        [{"span": "one"}, {"span": "two"}, {"span": "three"}],
    )

    assert outcome["status"] == "rejected"
    assert outcome["reason"] == "trace_event_limit"
    assert outcome["event_count"] == 2
    assert aggregator.get_trace("transition-1") is None


def test_trace_aggregation_concurrent_retry_records_single_terminal_outcome():
    aggregator = TraceAggregator(max_bytes=1024, max_events=10)
    barrier = threading.Barrier(5)
    outcomes = []

    def worker(index):
        barrier.wait()
        outcome = aggregator.aggregate(
            "run-1",
            "transition-1",
            [{"worker": index}],
        )
        outcomes.append(outcome)

    threads = [
        threading.Thread(target=worker, args=(index,))
        for index in range(5)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(outcomes) == 5
    assert len({outcome["timestamp"] for outcome in outcomes}) == 1
    assert len(aggregator.audit_records) == 5
    terminal = [
        r for r in aggregator.audit_records if r["decision"] == "terminal"
    ]
    idempotent = [
        r for r in aggregator.audit_records if r["decision"] == "idempotent"
    ]
    assert len(terminal) == 1
    assert len(idempotent) == 4


def test_trace_aggregation_rejects_unserializable_events():
    aggregator = TraceAggregator(max_bytes=1024, max_events=10)

    with pytest.raises(ValueError, match="JSON serializable"):
        aggregator.aggregate("run-1", "transition-1", [{"bad": object()}])

    assert aggregator.get_outcome("transition-1") is None
    assert aggregator.get_trace("transition-1") is None
