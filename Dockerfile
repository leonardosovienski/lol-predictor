FROM python:3.13.7-slim@sha256:5f55cdf0c5d9dc1a415637a5ccc4a9e18663ad203673173b8cda8f8dcacef689 AS build
WORKDIR /build
COPY . .
RUN python -m pip install --no-cache-dir build && python -m build --wheel

FROM python:3.13.7-slim@sha256:5f55cdf0c5d9dc1a415637a5ccc4a9e18663ad203673173b8cda8f8dcacef689
RUN useradd --create-home --uid 10001 predictor
COPY --from=build /build/dist/*.whl /tmp/
COPY --from=build /build/wheelhouse/*.whl /tmp/
RUN python -m pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl
USER predictor
WORKDIR /home/predictor
ENTRYPOINT ["lol-predictor"]
CMD ["health"]
HEALTHCHECK CMD ["lol-predictor", "health"]
