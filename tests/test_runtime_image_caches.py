from pathlib import Path

from scripts.validate_runtime_image_caches import validate_dockerfile


def test_repo_dockerfile_prunes_runtime_cache_dirs():
    assert validate_dockerfile(Path("Dockerfile")) == []


def test_missing_cache_cleanup_fails(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        """
        FROM python:3.11-slim AS builder
        RUN python -m pip install --no-cache-dir uv
        FROM python:3.11-slim AS runtime
        COPY --from=builder /app/dist/*.whl /tmp/wheels/
        RUN python -m pip install --no-cache-dir /tmp/wheels/*.whl
        """
    )

    errors = validate_dockerfile(dockerfile)

    assert "runtime stage does not remove /root/.cache" in errors
    assert "runtime stage does not remove /var/cache/apt" in errors
    assert "runtime stage does not remove /var/lib/apt/lists" in errors


def test_runtime_pip_install_without_no_cache_fails(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        """
        FROM python:3.11-slim AS builder
        RUN true
        FROM python:3.11-slim AS runtime
        COPY --from=builder /app/dist/*.whl /tmp/wheels/
        RUN python -m pip install /tmp/wheels/*.whl \
            && rm -rf /tmp/wheels /root/.cache \
                /var/cache/apt /var/lib/apt/lists
        """
    )

    errors = validate_dockerfile(dockerfile)

    assert any("pip install" in error for error in errors)


def test_runtime_whole_context_copy_fails(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        """
        FROM python:3.11-slim AS builder
        RUN true
        FROM python:3.11-slim AS runtime
        COPY --from=builder /app/dist/*.whl /tmp/wheels/
        COPY ./ /app/
        RUN python -m pip install --no-cache-dir /tmp/wheels/*.whl \
            && rm -rf /tmp/wheels /root/.cache \
                /var/cache/apt /var/lib/apt/lists
        """
    )

    errors = validate_dockerfile(dockerfile)

    assert "runtime stage must not copy the whole build context" in errors
