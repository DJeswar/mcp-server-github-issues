# Portable web image. `render.yaml` deploys it on Render Free; it also works locally and on any
# platform that can run a Dockerfile.
#
# ============================================================================================
# CREDENTIALS: NONE REQUIRED TO BUILD OR RUN.
# ============================================================================================
# The image defaults to ISSUES_BACKEND=fixture and LLM_BACKEND=stub, so the deployed Space works
# immediately with nothing configured. To point it at a live repository, add Space *secrets* --
# never bake them into this file or into an image layer. See docs/deploy.md.
#
#   docker build -t mcp-agent .
#   docker run --rm -p 7860:7860 mcp-agent
#   # then open http://localhost:7860

FROM python:3.14-slim

# Match the verified interpreter and CI. The official 3.14 slim image is now published; using
# one version across local tests, Actions and the container avoids a deployment-only resolver.

# The MCP Registry reads this annotation to verify image ownership if you ever publish the image
# as an `oci` package type. Harmless otherwise.
# >>> YOU DO THIS: replace DJeswar (or run scripts/set_identity.py) <<<
LABEL io.modelcontextprotocol.server.name="io.github.DJeswar/github-issues"
LABEL org.opencontainers.image.description="Live-Data MCP Agent: read-only GitHub issues agent with memory and injection guardrails"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # sensible, credential-free defaults -- override with Space secrets/variables
    ISSUES_BACKEND=fixture \
    LLM_BACKEND=stub \
    GUARDRAIL_MODE=enforce \
    MEMORY_DB=:memory: \
    PORT=7860

WORKDIR /app

# Dependencies first, so a code change does not invalidate the pip layer.
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt

COPY server/ ./server/
COPY agent/ ./agent/
COPY app/ ./app/

# Run as non-root on every host.
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 7860

# No shell form: exec form means signals reach Python, so the container stops promptly.
CMD ["python", "-m", "app.main"]
