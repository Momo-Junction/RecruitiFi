# Internal inference service. Build context: experiments/local_model/.
FROM python:3.12-slim-bookworm@sha256:0f086103b026048cc50cb5da25ec435c023c5241a83fc44daea593377abc61c4
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/tmp/huggingface \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
    TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 OTEL_SDK_DISABLED=true \
    OTEL_TRACES_EXPORTER=none OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none
WORKDIR /experiment
COPY requirements-linux.txt requirements.lock ./
COPY service/requirements.txt ./service/requirements.txt
RUN pip install --no-cache-dir --only-binary=:all: -c requirements.lock -r service/requirements.txt \
    && pip freeze > /experiment/installed-requirements.txt
COPY amd64_model_manifest.json ./
COPY models/all-MiniLM-L6-v2/tokenizer.json ./models/all-MiniLM-L6-v2/tokenizer.json
COPY models/all-MiniLM-L6-v2/onnx/model_quint8_avx2.onnx ./models/all-MiniLM-L6-v2/onnx/model_quint8_avx2.onnx
RUN python -c 'import hashlib,json,pathlib; m=json.loads(pathlib.Path("amd64_model_manifest.json").read_text()); root=pathlib.Path("models/all-MiniLM-L6-v2"); assert all((root/f["path"]).stat().st_size == f["bytes"] and hashlib.sha256((root/f["path"]).read_bytes()).hexdigest() == f["sha256"] for f in m["files"]), "Pinned model artifact mismatch"'
COPY service/__init__.py service/__main__.py service/model.py service/app.py service/test_service.py service/http_smoke.py ./service/
# All code/assets are readable by arbitrary UIDs; only /tmp may need writes.
RUN chmod -R a+rX /experiment
EXPOSE 8080
# Loopback is intentional; internal-container networking requires explicit opt-in.
CMD ["python", "-m", "service"]
