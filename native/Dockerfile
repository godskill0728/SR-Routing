FROM golang:1.24.13-bookworm AS go-toolchain
FROM python:3.12-slim-bookworm AS build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake pkg-config ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY --from=go-toolchain /usr/local/go /usr/local/go
ENV PATH="/usr/local/go/bin:${PATH}" GOTOOLCHAIN=auto GOMAXPROCS=4
RUN pip install --no-cache-dir openvino==2025.4.0 openvino-tokenizers==2025.4.0 transformers==4.57.6 sentencepiece && pip install --no-cache-dir torch==2.7.1 --index-url https://download.pytorch.org/whl/cpu
COPY semantic-router-0.3.0 /src
COPY native-libs /app/lib
RUN cmake -S /src/openvino-binding -B /src/openvino-binding/build -DCMAKE_BUILD_TYPE=Release && cmake --build /src/openvino-binding/build -j4 && cp -a /src/openvino-binding/build/libopenvino_semantic_router.so* /app/lib/
ENV LD_LIBRARY_PATH="/app/lib:/usr/local/lib/python3.12/site-packages/openvino/libs:/usr/local/lib/python3.12/site-packages/openvino_tokenizers/lib"
ENV CGO_LDFLAGS="-L/app/lib -Wl,-rpath-link,/app/lib -Wl,-rpath-link,/usr/local/lib/python3.12/site-packages/openvino/libs -Wl,-rpath-link,/usr/local/lib/python3.12/site-packages/openvino_tokenizers/lib"
WORKDIR /src/src/semantic-router
RUN go build -p 4 -tags=openvino -o /app/router-openvino ./cmd
COPY export_model.py /app/export_model.py
COPY entrypoint.sh /app/entrypoint.sh
FROM ubuntu:24.04 AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libstdc++6 curl ca-certificates libssl3t64 zlib1g libffi8 libbz2-1.0 liblzma5 libsqlite3-0 libreadline8t64 libexpat1 && rm -rf /var/lib/apt/lists/*
COPY --from=build /usr/local/bin /usr/local/bin
COPY --from=build /usr/local/lib /usr/local/lib
RUN ldconfig
COPY --from=build /app /app
ENV LD_LIBRARY_PATH="/app/lib:/usr/local/lib/python3.12/site-packages/openvino/libs:/usr/local/lib/python3.12/site-packages/openvino_tokenizers/lib"
ENV OPENVINO_TOKENIZERS_LIB=/usr/local/lib/python3.12/site-packages/openvino_tokenizers/lib/libopenvino_tokenizers.so
WORKDIR /app
ENTRYPOINT ["bash", "/app/entrypoint.sh"]