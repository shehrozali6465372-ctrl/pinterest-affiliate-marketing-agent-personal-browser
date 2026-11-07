FROM mcr.microsoft.com/playwright/python:v1.55.0-noble
WORKDIR /app
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PYTHONUNBUFFERED=1
COPY services/ucos_browser/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && PLAYWRIGHT_BROWSERS_PATH=/ms-playwright python -m playwright install chromium \
    && test -d /ms-playwright
COPY services/ucos_browser ./services/ucos_browser
CMD ["/bin/sh", "-c", "export PLAYWRIGHT_BROWSERS_PATH=/ms-playwright; exec python services/ucos_browser/server.py"]
