# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
.DEFAULT_GOAL := stas
BUILD-DIR     := .build
DEB-PKG-DIR   := ${BUILD-DIR}/deb-pkg
RPM-PKG-DIR   := ${BUILD-DIR}/rpm-pkg

${BUILD-DIR}:
	./configure
	@echo "Configuration located in: $@"
	@echo "-------------------------------------------------------"

.PHONY: stas
stas: ${BUILD-DIR}
	ninja -C ${BUILD-DIR}

.PHONY: clean
clean:
ifneq ("$(wildcard ${BUILD-DIR})","")
	ninja -C ${BUILD-DIR} -t clean
endif

.PHONY: purge
purge:
ifneq ("$(wildcard ${BUILD-DIR})","")
	rm -rf ${BUILD-DIR}
endif

.PHONY: install test
install test: ${BUILD-DIR}
	cd ${BUILD-DIR} && meson $@

.PHONY: dist
dist: ${BUILD-DIR}
	cd ${BUILD-DIR} && meson $@

.PHONY: loc
loc:
	@cloc --by-file --exclude-dir=${BUILD-DIR},Documentation,test,utils,debian,obj-x86_64-linux-gnu,.github --exclude-lang=Markdown,"NAnt script",XML,"Bourne Again Shell",make,"Bourne Shell",Meson,YAML,XSLT .

.PHONY: loc-full
loc-full:
	@cloc --by-file --exclude-dir=${BUILD-DIR},Documentation,test,utils,debian,obj-x86_64-linux-gnu,.github .


# THE FOLLOWING TARGETS ARE EXPERIMENTAL:
# Use "DEB_BUILD_OPTIONS=nocheck make debian" to skip unit testing.
.PHONY: deb
deb: ${BUILD-DIR}
	mkdir -p ${DEB-PKG-DIR}
	dpkg-buildpackage -us -uc
	@mv ../nvme-stas_*.deb ${DEB-PKG-DIR}
	@mv ../nvme-stas_*.buildinfo ${DEB-PKG-DIR}
	@mv ../nvme-stas_*.changes ${DEB-PKG-DIR}
	@mv ../nvme-stas_*.dsc ${DEB-PKG-DIR}
	@mv ../nvme-stas_*.tar.gz ${DEB-PKG-DIR}
	@echo "======================================================="
	@echo "Debian packages located in: ${DEB-PKG-DIR}/"

.PHONY: rpm
rpm: dist
	rpmbuild ${BUILD-DIR}/nvme-stas.spec
