FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Production image installs requirements.txt only; compose passes
# requirements-dev.txt for the development stack.
ARG REQUIREMENTS=requirements.txt
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r ${REQUIREMENTS}

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 tcos
COPY --chown=tcos:tcos . .
USER tcos

EXPOSE 8000

# Production default. The development compose file overrides this command.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
