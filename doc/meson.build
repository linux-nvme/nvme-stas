# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
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
            docbooks += [ [stem, manvolnum, files(fname), deps] ]
        endforeach
    endif

    # Generate DocBooks from IDL queried directly from the D-Bus services.
    # gdbus-codegen writes one DocBook per D-Bus interface, named after that
    # interface, and each IDL declares the daemon's interface plus its .debug
    # companion. They are built by a custom_target so that the man and html
    # targets can take them by reference: passing a generated file by name is
    # a hard error in Meson 2.0.
    env = environment({'PYTHONPATH': conf.get('PYTHONPATH')})
    dbus_idls = [
        [ stafd_idl, [ conf.get('STAFD_DBUS_NAME'), conf.get('STAFD_DBUS_NAME') + '.debug' ] ],
        [ stacd_idl, [ conf.get('STACD_DBUS_NAME'), conf.get('STACD_DBUS_NAME') + '.debug' ] ],
    ]
    foreach tuple : dbus_idls
        idl   = tuple[0]
        stems = tuple[1]

        outputs = []
        foreach stem : stems
            outputs += stem + '.xml'
        endforeach

        idl_docbooks = custom_target(
            'docbooks-' + stems[0],
            input: idl,
            output: outputs,
            command: [
                dbus2doc,
                '--idl', '@INPUT@',
                '--output-directory', '@OUTDIR@',
                '--tmp', '@PRIVATE_DIR@',
            ],
            env: env,
        )

        i = 0
        foreach stem : stems
            docbooks += [ [stem, '5', idl_docbooks[i], []] ]
            i += 1
        endforeach
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
        file = tuple[2]
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
