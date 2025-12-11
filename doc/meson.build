# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#


if want_man or want_html or want_readthedocs
    docbklst = find_program('genlist-from-docbooks.py')
    dbus2doc = find_program('dbus-idl-to-docbooks.py')
    dbusgen  = find_program('gdbus-codegen', required: false) # Needed by dbus2doc
    if not dbusgen.found()
        error('gdbus-codegen missing: Install libglib2.0-dev (deb) / glib2-devel (rpm)')
    endif

    # Get the list of DocBook files to process. The result will
    # be saved to variable docbooks as a list of tuples as follows:
    # docbooks = [ ['file1', 'manvolnum-from-file1.xml', 'file1.xml'],
    #              ['file2', 'manvolnum-from-file2.xml', 'file2.xml'], ... ]
    docbooks = []
    rr = run_command(docbklst, check: true)
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

    # Generate DocBooks from IDL queried directly from the D-Bus services.
    out_dir = conf.get('BUILD_DIR') / 'man-tmp'
    env = environment({'PYTHONPATH': conf.get('PYTHONPATH')})
    idls = [ 'stafd.idl', 'stacd.idl' ]
    foreach idl : idls
        rr = run_command(
            dbus2doc,
            '--idl', conf.get('BUILD_DIR') / 'staslib' / idl,
            '--output-directory', out_dir,
            '--tmp', meson.current_build_dir(),
            env: env,
            check: true)
        output = rr.stdout().strip()
        if output != ''
            foreach stem : output.split(';')
                docbooks += [ [stem, '5', out_dir / stem + '.xml', []] ]
            endforeach
        endif
    endforeach


    xsltproc = find_program('xsltproc')
    if xsltproc.found()
        manpage_style = 'http://docbook.sourceforge.net/release/xsl/current/manpages/docbook.xsl'
        if run_command(xsltproc, '--nonet', manpage_style, check: false).returncode() != 0
            error('Docbook style sheet missing: Install docbook-xsl (deb) / docbook-style-xsl (rpm)')
        endif
    endif

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

    man_xsl  = files('man.xsl')
    html_xsl = files('html.xsl')


    html_files = [] # Will be used as input to readthedocs
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
                install: true,
                install_dir: mandir / ('man' + sect)
            )
        endif

        if want_html or want_readthedocs
            html = stem + '.html'
            html_file = custom_target(
                html,
                input: file,
                output: html,
                depend_files: deps,
                command: xslt_cmd + [html_xsl, '@INPUT@'],
                install: want_html,
                install_dir: docdir / 'html'
            )
            html_files += [ [stem, html_file ] ]
        endif
    endforeach
endif

if want_readthedocs
    subdir('readthedocs')
endif
