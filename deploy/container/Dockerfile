# The aops server outside Databricks Apps (docs/container.md).
#   docker build -f deploy/container/Dockerfile -t aops-server .
#   docker run --env-file aops.env -p 8000:8000 aops-server
# The server's own identity, the registry and the login come from the environment; nothing secret is in the image.
FROM python:3.11-slim

ARG DATABRICKS_CLI_VERSION=1.21.0
ARG TARGETARCH
# The databricks CLI: `agentbricks deploy` (code-based agents) drives it with the server's own credentials
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl unzip \
 && arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
 && curl -fsSL -o /tmp/cli.zip \
    "https://github.com/databricks/cli/releases/download/v${DATABRICKS_CLI_VERSION}/databricks_cli_${DATABRICKS_CLI_VERSION}_linux_${arch}.zip" \
 && unzip -q /tmp/cli.zip databricks -d /usr/local/bin \
 && rm /tmp/cli.zip \
 && apt-get purge -y curl unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Behind a package mirror: --build-arg PIP_INDEX_URL=https://<mirror>/simple (pip and uv both use it)
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY . /tmp/aops
RUN PIP_INDEX_URL="$PIP_INDEX_URL" pip install --no-cache-dir uv "/tmp/aops[serve,dbx]" && rm -rf /tmp/aops

# agentbricks in its own environment, installed now rather than at the first code deploy
ENV AOPS_AGENTBRICKS_VENV=/opt/agentbricks
RUN UV_DEFAULT_INDEX="$PIP_INDEX_URL" python -c "from aops.dbx import code; code.agentbricks_cli()"

RUN useradd --create-home --uid 10001 aops
USER aops
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/meta/health', timeout=4)"
CMD ["aops", "serve", "--host", "0.0.0.0", "--port", "8000"]
