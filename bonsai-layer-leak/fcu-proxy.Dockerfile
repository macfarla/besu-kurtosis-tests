FROM python:3.12-slim
RUN pip install --no-cache-dir aiohttp
COPY engine-api-fcu-proxy.py /proxy.py
COPY fcu-proxy-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
