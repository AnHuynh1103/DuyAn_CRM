# Sử dụng Ubuntu 24.04 (Noble) làm nền
FROM ubuntu:noble

# Thiết lập ngôn ngữ
ENV LANG=en_US.UTF-8

# Cài đặt các gói hệ thống cần thiết
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive \
    apt-get install -y --no-install-recommends \
        ca-certificates curl git gnupg build-essential \
        python3-dev python3-pip python3-wheel python3-venv \
        libldap2-dev libsasl2-dev libssl-dev libxml2-dev libxslt1-dev \
        libjpeg-dev libpq-dev postgresql-client && \
    rm -rf /var/lib/apt/lists/*

# Cài đặt wkhtmltopdf
ARG TARGETARCH=amd64
RUN apt-get update && \
    # Cài đặt trước các gói phụ thuộc mà wkhtmltox yêu cầu
    apt-get install -y --no-install-recommends \
        fontconfig \
        libfreetype6 \
        libx11-6 \
        libxcb1 \
        libxext6 \
        libxrender1 \
        xfonts-75dpi \
        xfonts-base && \
    WKHTMLTOPDF_ARCH=${TARGETARCH} && \
    case ${TARGETARCH} in \
    "amd64") WKHTMLTOPDF_SHA=967390a759707337b46d1c02452e2bb6b2dc6d59  ;; \
    "arm64") WKHTMLTOPDF_SHA=90f6e69896d51ef77339d3f3a20f8582bdf496cc  ;; \
    esac \
    && curl -o wkhtmltox.deb -sSL https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.jammy_${WKHTMLTOPDF_ARCH}.deb \
    && echo "${WKHTMLTOPDF_SHA} wkhtmltox.deb" | sha1sum -c - \
    && apt-get install -y --no-install-recommends ./wkhtmltox.deb \
    && rm -rf /var/lib/apt/lists/* wkhtmltox.deb

# Cài đặt nodejs và các công cụ CSS
RUN curl -sL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g rtlcss

# Tạo user 'odoo'
RUN useradd -m -d /home/odoo -s /bin/bash odoo

# Thiết lập thư mục làm việc bên trong container
WORKDIR /opt/odoo

# THAY ĐỔI: Sao chép file requirements.txt từ thư mục odoo18 ở cấp trên
# Dấu '..' có nghĩa là đi lên một cấp thư mục từ 'context' (tức là từ /box18/ lên /odoo-crm/)
COPY ./odoo18-requirements.txt .

# Cài đặt các thư viện Python
RUN pip3 install --no-cache-dir --break-system-packages -r odoo18-requirements.txt

# Tạo thư mục cho filestore và cấp quyền
# Cấp quyền cho cả thư mục mã nguồn sẽ được mount vào
RUN mkdir -p /var/lib/odoo /mnt/extra-addons && \
    chown -R odoo:odoo /var/lib/odoo /mnt/extra-addons /opt/odoo

# Sao chép entrypoint script vào trong image
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

USER root

# Cấp quyền thực thi cho script
RUN chmod +x /usr/local/bin/entrypoint.sh
RUN chown -R odoo:odoo /var/lib/odoo


# Chuyển sang user odoo
USER root


# Thiết lập script làm entrypoint
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]


# Mở cổng
EXPOSE 8069
EXPOSE 8072

# Lệnh mặc định khi container khởi chạy
CMD ["./odoo-bin", "--config=/etc/odoo/odoo.conf", "--dev=all"]