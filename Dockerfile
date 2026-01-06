FROM python:3.13-slim AS base

ARG USER_ID=1001
ARG GROUP_ID=1001
ARG TERRAFORM_VERSION="1.14.3"
ARG TERRAFORM_ARCH="amd64"


ENV HOME=/home/appuser \
    TERRAFORM_INSTALL_DIR="/opt/terraform"
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_VENV_CLEAR=1 \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV="/app/.venv" \
    PATH="${HOME}/.local/bin:/app/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${TERRAFORM_INSTALL_DIR}" \
    ZSH_DISABLE_COMPFIX="true"

COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /uvx /bin/

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        make \
        unzip \
        wget \
        zsh \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g $GROUP_ID appgroup && \
    useradd -u $USER_ID -g appgroup -s /bin/bash -m -d $HOME appuser

RUN mkdir -p "${HOME}" && \
    chown -R appuser:appgroup "${HOME}" && \
    chmod 755 "${HOME}"

WORKDIR /app
COPY --chown=appuser:appgroup . .
RUN chown -R appuser:appgroup /app
RUN mkdir -p /app/.git/hooks && chmod -R u+rwX /app/.git/hooks

# Install Terraform
RUN mkdir -p ${TERRAFORM_INSTALL_DIR} && \
    wget -q https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TERRAFORM_ARCH}.zip -O /tmp/terraform.zip && \
    unzip -d ${TERRAFORM_INSTALL_DIR} /tmp/terraform.zip && \
    rm /tmp/terraform.zip

USER appuser

# Configure git for the non-root user
RUN git config --global --add safe.directory /app

# Install Oh My Zsh
RUN sh -c "$(wget -O- https://github.com/deluan/zsh-in-docker/releases/download/v1.2.1/zsh-in-docker.sh)" \
    -p git \
    -p ssh-agent \
    -p https://github.com/zsh-users/zsh-autosuggestions \
    -p https://github.com/zsh-users/zsh-completions \
    -p https://github.com/zsh-users/zsh-syntax-highlighting.git \
    -p git-auto-fetch

# Install Atuin
RUN curl --proto '=https' --tlsv1.2 -LsSf https://setup.atuin.sh | sh && \
    echo 'eval "$(atuin init zsh)"' >> "${HOME}/.zshrc"

# Install Python dependencies as the non-root user
RUN UV_VENV_OVERWRITE=1 uv venv --python /usr/local/bin/python && \
    uv sync --extra=dev && \
    uv run prek install && \
    uv run prek install --install-hooks

USER root
RUN sed -i "s|appuser:x:${USER_ID}:${GROUP_ID}:${HOME}:/bin/bash|appuser:x:${USER_ID}:${GROUP_ID}:${HOME}:$(which zsh)|" /etc/passwd
USER appuser

CMD ["zsh"]
