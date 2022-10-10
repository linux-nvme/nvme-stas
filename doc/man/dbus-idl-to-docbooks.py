#!/usr/bin/python3
import os
import sys
import pathlib
import tempfile
import subprocess
from argparse import ArgumentParser
from lxml import etree

print('===============================================================')
print('\n'.join(sys.path))
print('===============================================================')


def parse_args():
    parser = ArgumentParser(description='Extract D-Bus IDL from executable and genarate DocBook documentation.')
    parser.add_argument(
        '--executable',
        action='store',
        help='Executable from which to get the IDL (must provide an --idl option)',
        required=True,
        type=str,
        metavar='FILE',
    )
    parser.add_argument(
        '--output-directory',
        action='store',
        help='Output directory where DocBook files will be saved',
        required=True,
        type=str,
        metavar='DIR',
    )
    parser.add_argument(
        '--tmp',
        action='store',
        help='Temporary directory for intermediate files',
        required=True,
        type=str,
        metavar='DIR',
    )
    return parser.parse_args()


ARGS = parse_args()

if not os.path.exists(ARGS.executable):
    print(f'Executable does not exist: {ARGS.executable}')

if not os.path.exists(ARGS.output_directory):
    print(f'Output dir does not exist: {ARGS.output_directory}')

if not os.path.exists(ARGS.tmp):
    print(f'Temp. dir does not exist: {ARGS.tmp}')


pathlib.Path(ARGS.output_directory).mkdir(parents=True, exist_ok=True)

REF_ENTRY_INFO = '''\
  <refentryinfo>
    <title>stafctl</title>
    <productname>nvme-stas</productname>
    <author>
      <personname>
        <honorific>Mr</honorific>
        <firstname>Martin</firstname>
        <surname>Belanger</surname>
      </personname>
      <affiliation>
        <orgname>Dell, Inc.</orgname>
      </affiliation>
    </author>
  </refentryinfo>
'''

MANVOLNUM = '<manvolnum>5</manvolnum>'

try:
    PARSER = etree.XMLParser(remove_blank_text=True)
except Exception as ex:
    print(f'Failed to create PARSER: {ex}')
    raise



def add_missing_info(fname, stem):
    xml = etree.parse(fname, PARSER)
    root = xml.getroot()
    if root.tag != 'refentry':
        return

    if xml.find('refentryinfo'):
        return

    root.insert(0, etree.fromstring(REF_ENTRY_INFO))

    refmeta = xml.find('refmeta')
    if refmeta is not None:
        refmeta.append(etree.fromstring(f'<refentrytitle>{stem}</refentrytitle>'))
        refmeta.append(etree.fromstring(MANVOLNUM))

    et = etree.ElementTree(root)
    et.write(fname, pretty_print=True)


FILE_PREFIX = 'nvme-stas'
FINAL_PREFIX = FILE_PREFIX + '-'

try:
    pathlib.Path(ARGS.tmp).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ARGS.tmp) as tmpdirname:
        idl_file = os.path.join(tmpdirname, 'dbus.idl')
        try:
            subprocess.run([ARGS.executable, '--idl', idl_file], check=True)
        except subprocess.CalledProcessError as ex:
            print(f'Error: {ex}')
            sys.exit(f'Failed to generate IDL file. {ex}')

        try:
            subprocess.run(['gdbus-codegen', '--output-directory', tmpdirname, '--generate-docbook', FILE_PREFIX, idl_file])
        except subprocess.CalledProcessError as ex:
            print(f'Error: {ex}')
            sys.exit(f'Failed to generate DocBook file. {ex}')

        stems = []
        with os.scandir(tmpdirname) as it:
            for entry in it:
                if entry.is_file() and entry.name.endswith('.xml') and entry.name.startswith(FINAL_PREFIX):
                    fname = entry.name[len(FINAL_PREFIX) :]  # Strip prefix
                    stem = fname[0:-4]  # Strip '.xml' suffix
                    stems.append(stem)
                    tmp_file = os.path.join(tmpdirname, entry.name)
                    add_missing_info(tmp_file, stem)
                    os.replace(tmp_file, os.path.join(ARGS.output_directory, fname))

        print(';'.join(stems))
except Exception as ex:
    print(f'Fail to run main loop: {ex}')
    raise

