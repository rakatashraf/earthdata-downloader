FROM ghcr.io/osgeo/gdal:ubuntu-full-latest

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-numpy ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY converter/server.py /app/server.py

ENV PORT=8080
EXPOSE 8080
CMD ["python3", "/app/server.py"]
