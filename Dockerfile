FROM python:3.12-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends gcc make libc6-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY core core
RUN make -C core build/libaggregator.so && make -C core test

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY meterflow meterflow
RUN pip install --no-cache-dir .
COPY --from=build /src/core/build/libaggregator.so core/build/libaggregator.so
ENV METERFLOW_LIB=/app/core/build/libaggregator.so
EXPOSE 8000
CMD ["python", "-m", "meterflow.cli", "serve"]
