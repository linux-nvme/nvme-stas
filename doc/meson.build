# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#

if want_man or want_html
    xsltproc = find_program('xsltproc')
    dbus2doc = find_program('man/dbus-idl-to-docbooks.py')
    docbklst = find_program('man/genlist-from-docbooks.py')
    dbusgen  = find_program('gdbus-codegen')

    if xsltproc.found()
        manpage_style = 'http://docbook.sourceforge.net/release/xsl/current/manpages/docbook.xsl'
        if run_command(xsltproc, '--nonet', manpage_style, check: false).returncode() != 0
            error('Manpage style sheet cannot be found (package docbook-xsl missing)')
        endif
    endif

    # Get the list of DocBook files to process. The result will
    # be saved to variable docbooks as a list of tuples as follows:
    # docbooks = [ ['file1', 'manvolnum-from-file1.xml', 'file1.xml'],
    #              ['file2', 'manvolnum-from-file2.xml', 'file2.xml'], ... ]
    docbooks = []
    rr = run_command(docbklst, check: false)
    output = rr.stdout().strip()
    if output != ''
        foreach item : output.split(';')
            items     = item.split(',')
            stem      = items[0]
            manvolnum = items[1]
            fname     = items[2]
            deps      = items[3]
            if deps == 'None'
                deps = []
            else
                deps = deps.split(':')
            endif
            docbooks += [ [stem, manvolnum, fname, deps] ]
        endforeach
    endif

    tmp_dir = meson.build_root() / 'man-tmp'

    # Generate DocBooks from IDL queried directly from the D-Bus services.
    dbus_services = [ stafd, stacd ]
    env = environment({'PYTHONPATH': meson.build_root()})
    foreach service : dbus_services
        rr = run_command(
            dbus2doc,
            '--executable', service,
            '--output-directory', tmp_dir,
            '--tmp', meson.current_build_dir(),
            env: env,
            check: true)
        output = rr.stdout().strip()
        if output != ''
            foreach stem : output.split(';')
                docbooks += [ [stem, '5', tmp_dir / stem + '.xml', []] ]
            endforeach
        endif
    endforeach

    xslt_cmd = [
      xsltproc,
      '--nonet',
      '--xinclude',
      '--stringparam', 'man.output.quietly', '1',
      '--stringparam', 'funcsynopsis.style', 'ansi',
      '--stringparam', 'man.th.extra1.suppress', '1',
      '--stringparam', 'man.authors.section.enabled', '0',
      '--stringparam', 'man.copyright.section.enabled', '0',
      '--stringparam', 'nvme-stas.version', '@0@'.format(meson.project_version()),
      '-o', '@OUTPUT@',
    ]

    man_xsl  = files('man/man.xsl')
    html_xsl = files('man/html.xsl')

    foreach tuple: docbooks
        stem = tuple[0]
        sect = tuple[1]
        file = files(tuple[2])
        deps = tuple[3]

        if want_man
            man = stem + '.' + sect
            custom_target(
                man,
                input: file,
                output: man,
                depend_files: deps,
                command: xslt_cmd + [man_xsl, '@INPUT@'],
                install: want_man,
                install_dir: join_paths(get_option('mandir'), ('man' + sect))
            )
        endif

        if want_html
            html = stem + '.html'
            custom_target(
                html,
                input: file,
                output: html,
                depend_files: deps,
                command: xslt_cmd + [html_xsl, '@INPUT@'],
                install: want_html,
                install_dir: join_paths(docdir, 'html')
            )
        endif
    endforeach
endif
