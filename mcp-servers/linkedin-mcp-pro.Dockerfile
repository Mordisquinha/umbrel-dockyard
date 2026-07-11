FROM python:3.13-slim

WORKDIR /app

COPY vendor/linkedin-mcp-pro/pyproject.toml ./
COPY vendor/linkedin-mcp-pro/linkedin_mcp/ ./linkedin_mcp/
COPY vendor/linkedin-mcp-pro/README.md vendor/linkedin-mcp-pro/LICENSE ./

RUN pip install --no-cache-dir -e . \
    && apt-get update \
    && apt-get install --no-install-recommends -y curl nodejs npm \
    && npm install --global supergateway@3.4.3 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/data

ENTRYPOINT ["supergateway"]
CMD ["--stdio", "python3 -m linkedin_mcp.server", "--outputTransport", "streamableHttp", "--port", "8765", "--streamableHttpPath", "/mcp", "--healthEndpoint", "/healthz", "--logLevel", "info"]
