FROM fedora:41

WORKDIR /root

# first line for nvme-stas
# second line for libnvme
RUN dnf install -y python3-dasbus python3-pyudev python3-systemd python3-gobject meson \
                   git gcc g++ cmake openssl-devel libuuid-devel json-c-devel swig python-devel meson && dnf clean all

COPY . .
RUN meson .build && ninja -C .build && meson install -C .build

ENTRYPOINT ["python3"]
