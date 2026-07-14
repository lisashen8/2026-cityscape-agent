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

RUN adduser --disabled-password --gecos "" myuser

COPY . .

COPY --from=genmedia-mcp-builder /app/mcp-gemini-go /app/tools/mcp-gemini-go 

RUN chown -R myuser:myuser /app

USER myuser

ENV PATH="/home/myuser/.local/bin:/app/tools:$PATH"

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]