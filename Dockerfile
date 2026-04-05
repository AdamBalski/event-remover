FROM python:3.12-slim

WORKDIR /app

ENV PORT=8080
ENV BASE_URL=http://localhost:8080

COPY matching.py run.py ui.html ./

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python3 -c "import os, sys, urllib.request; port = os.environ.get('PORT', '8080'); response = urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=2); sys.exit(0 if response.read() == b'OK' else 1)"

CMD ["python3", "-u", "run.py"]
