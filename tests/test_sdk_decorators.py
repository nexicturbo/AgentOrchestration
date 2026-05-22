import pytest

from src.sdk.decorators import task


def test_task_accepts_non_negative_integer_retries():
    def handler():
        return "ok"

    decorated = task(retries=2, timeout=10)(handler)

    assert decorated.__task_config__ == {
        "name": "handler",
        "retries": 2,
        "timeout": 10,
    }


@pytest.mark.parametrize("invalid_retries", [-1, 1.5, "3", True])
def test_task_rejects_invalid_retry_counts_before_config(invalid_retries):
    def handler():
        return "ok"

    with pytest.raises(ValueError, match="non-negative integer"):
        task(retries=invalid_retries)(handler)

    assert not hasattr(handler, "__task_config__")
