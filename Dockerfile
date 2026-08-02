FROM python:3.13.14-alpine3.24@sha256:399babc8b49529dabfd9c922f2b5eea81d611e4512e3ed250d75bd2e7683f4b0 AS build
RUN apk add --no-cache build-base
WORKDIR /build
COPY . .
RUN python -m pip install --no-cache-dir build && python -m build --wheel

FROM python:3.13.14-alpine3.24@sha256:399babc8b49529dabfd9c922f2b5eea81d611e4512e3ed250d75bd2e7683f4b0
RUN adduser -S -D -u 10001 -h /home/predictor predictor
COPY --from=build /build/dist/*.whl /tmp/
RUN python -m pip install --no-cache-dir /tmp/*.whl \
        "predictor-core @ https://github.com/leonardosovienski/core-predictor/releases/download/v2.1.0/predictor_core-2.1.0-py3-none-any.whl" \
        "predictor-ops @ https://github.com/leonardosovienski/tools-predictor/releases/download/v2.0.1/predictor_ops-2.0.1-py3-none-any.whl" \
    && rm /tmp/*.whl
USER predictor
WORKDIR /home/predictor
ENTRYPOINT ["lol-predictor"]
CMD ["health"]
HEALTHCHECK CMD ["lol-predictor", "health"]
