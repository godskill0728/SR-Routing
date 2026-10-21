FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8080
WORKDIR /opt/sr
COPY portal ./portal
COPY reports-public ./reports-public
USER 65532:65532
EXPOSE 8080
CMD ["python", "-B", "portal/fill_release.py"]