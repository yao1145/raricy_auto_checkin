FROM python:3.13-slim

# tzdata：config.json 的 schedule.timezone 是 Asia/Shanghai，缺它 APScheduler 解析时区会报错
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖先于源码 COPY，改代码不会失效依赖层缓存
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY run.py ./
COPY backend/ backend/
COPY frontend/ frontend/

# 非 root 运行；uid 固定 1000，宿主机数据目录要 chown 成同一个 uid
RUN useradd -u 1000 -m appuser \
 && mkdir -p /app/runtime \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

# slim 镜像没有 curl，用 python 自带的 urllib 做健康检查，不为一个探针多装包
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=4).status == 200 else 1)"

# 容器内必须绑 0.0.0.0：容器回环与宿主机不是同一网卡，绑 127.0.0.1 会导致端口发布不通。
# 对外只暴露到宿主机回环由 docker-compose 的 127.0.0.1:5000:5000 负责。
# 单进程是硬要求：多 worker 会各起一份 APScheduler，导致重复打卡。
CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "5000", "--no-browser"]
