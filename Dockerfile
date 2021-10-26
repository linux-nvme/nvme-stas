##########################################################################################
ARG registry=library
ARG base=fedora
ARG version=33
FROM $registry/$base:$version as libnvme-builder

WORKDIR /root

# TODO: once libnvme project has a package or docker image, remove this stage and install libnvme
RUN dnf install -y git gcc g++ cmake libuuid-devel json-c-devel swig python-devel meson
ARG GITHUB_ORG=linux-nvme
ARG GITHUB_REPO=libnvme
ARG GITHUB_TOKEN
RUN git clone https://${GITHUB_TOKEN}github.com/${GITHUB_ORG}/${GITHUB_REPO} && \
    cd ${GITHUB_REPO} && meson .build && ninja -C .build && cd .build && DESTDIR=/root/install meson install

##########################################################################################
ARG registry=library
ARG base=fedora
ARG version=33
FROM $registry/$base:$version

WORKDIR /root

RUN dnf install -y python3-dasbus python3-pyudev python3-systemd python3-gobject meson
COPY . .
RUN meson .build && ninja -C .build && cd .build && meson install

# TODO: once libnvme project has a package, use: dnf install -y libnvme
COPY --from=libnvme-builder /root/install /

ENTRYPOINT ["python3"]
