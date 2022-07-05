FROM fedora:33

WORKDIR /root

# for nvme-stas
RUN dnf install -y python3-dasbus python3-pyudev python3-systemd python3-gobject meson
# for libnvme
RUN dnf install -y git gcc g++ cmake openssl-devel libuuid-devel json-c-devel swig python-devel meson

COPY . .
RUN meson .build && ninja -C .build && cd .build && meson install

ENTRYPOINT ["python3"]
