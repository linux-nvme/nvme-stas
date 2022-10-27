# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
.DEFAULT_GOAL     := stas
BUILD-DIR         := .build
DEB-PKG-DIR       := ${BUILD-DIR}/deb-pkg
RPM-BUILDROOT-DIR := ${BUILD-DIR}/rpmbuild

.PHONY: update-subprojects
update-subprojects:
	meson subprojects update

${BUILD-DIR}:
	BUILD_DIR=${BUILD-DIR} ./configure
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

.PHONY: install
install: stas
	sudo meson $@ -C ${BUILD-DIR} --skip-subprojects

.PHONY: uninstall
uninstall: ${BUILD-DIR}
	sudo ninja -C ${BUILD-DIR} uninstall

.PHONY: dist
dist: stas
	meson $@ -C ${BUILD-DIR} --formats gztar

.PHONY: test
test: stas
	meson $@ -C ${BUILD-DIR} --suite nvme-stas

.PHONY: loc
loc:
	@cloc --by-file --exclude-dir=${BUILD-DIR},doc,subprojects,test,utils,debian,obj-x86_64-linux-gnu,.github --exclude-lang=Markdown,"NAnt script",XML,"Bourne Again Shell",make,"Bourne Shell",Meson,YAML,XSLT .

.PHONY: loc-full
loc-full:
	@cloc --by-file --exclude-dir=${BUILD-DIR},subprojects,debian,obj-x86_64-linux-gnu,.github .

# Coverage requirements:
#   pip install coverage
.PHONY: coverage
coverage: stas
	cd ${BUILD-DIR} && ./coverage.sh

################################################################################
# Debian (*.deb)
# Use "DEB_BUILD_OPTIONS=nocheck make deb" to skip unit testing.
# This requires: sudo apt install -y debhelper dh-python
ifeq (deb,$(strip $(MAKECMDGOALS)))
  ifneq (SUCCESS,$(shell dpkg -s debhelper dh-python > /dev/null 2>&1 && echo "SUCCESS" || echo "FAIL"))
    $(error Missing packages. Run -> "sudo apt install -y debhelper dh-python")
  endif
endif

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


################################################################################
# RedHat (*.rpm)
${BUILD-DIR}/nvme-stas.spec: ${BUILD-DIR} nvme-stas.spec.in
	meson --reconfigure ${BUILD-DIR}

${RPM-BUILDROOT-DIR}: ${BUILD-DIR}/nvme-stas.spec
	rpmbuild -ba $< --build-in-place --clean --nocheck --define "_topdir $(abspath ${BUILD-DIR}/rpmbuild)"
	@echo "======================================================="
	@echo "RPM packages located in: ${RPM-BUILDROOT-DIR}/"

.PHONY: rpm
rpm: ${RPM-BUILDROOT-DIR}
