FROM fedora:36 as base
RUN dnf install -y python3-dasbus python3-pyudev python3-systemd python3-gobject

FROM base as builder
RUN dnf install -y git gcc g++ cmake openssl-devel libuuid-devel json-c-devel swig python-devel meson

COPY . .
RUN meson .build && ninja -C .build && meson install -C .build --destdir=/root/stas-dest

FROM base
COPY --from=builder /root/stas-dest /root/stas-dest
ENTRYPOINT ["python3"]
