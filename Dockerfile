FROM golang:1.26 AS genmedia-mcp-builder

WORKDIR /app

RUN git clone https://github.com/GoogleCloudPlatform/vertex-ai-creative-studio.git

WORKDIR /app/vertex-ai-creative-studio/experiments/mcp-genmedia/mcp-genmedia-go/mcp-gemini-go

RUN go mod download

RUN CGO_ENABLED=0 GOOS=linux go build -o /app/mcp-gemini-go

FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

COPY --from=genmedia-mcp-builder /app/mcp-gemini-go /app/tools/mcp-gemini-go 

# Note: We do NOT create or switch to a non-root user here. The container must 
# run as root because the Cloud Run `sandbox do --allow-egress` command requires 
# elevated privileges to create isolated network namespaces (/var/run/netns) 
# to provide internet access to the sandboxed execution environment.
ENV PATH="/root/.local/bin:/app/tools:$PATH"

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]