ARG registry=library
ARG base=fedora
ARG version=33
FROM $registry/$base:$version

WORKDIR /root

# for nvme-stas
RUN dnf install -y python3-dasbus python3-pyudev python3-systemd python3-gobject python3-netifaces meson
# for libnvme
RUN dnf install -y git gcc g++ cmake openssl-devel libuuid-devel json-c-devel swig python-devel meson

COPY . .
RUN meson .build && ninja -C .build && cd .build && meson install

ENTRYPOINT ["python3"]
