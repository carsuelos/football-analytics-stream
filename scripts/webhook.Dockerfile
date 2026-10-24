# The stand-in webhook (scripts/webhook_echo.py) as an image, for where there is
# nothing to mount it from: in Azure it receives the notifier's alerts when no
# real webhook is configured, and prints them to the logs. Build context: scripts/.
FROM python:3.13-slim
COPY webhook_echo.py /webhook_echo.py
USER nobody
EXPOSE 9000
ENTRYPOINT ["python", "/webhook_echo.py", "--host", "0.0.0.0"]
