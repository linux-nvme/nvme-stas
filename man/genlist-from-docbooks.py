#!/usr/bin/python3
import glob
from lxml import etree

exclude_list = list(glob.glob("standard-*.xml"))

PARSER = etree.XMLParser(remove_blank_text=True)


def extract_data(fname):
    et = etree.parse(fname, PARSER)

    manvolnum = et.find("./refmeta/manvolnum")
    manvolnum = manvolnum.text if manvolnum is not None else 0

    deps = set()
    for elem in et.iter():
        keys = elem.keys()
        if "href" in keys and "xpointer" in keys:
            dep = elem.values()[0]
            if dep in exclude_list:
                deps.add(dep)

    return manvolnum, list(deps)


output = list()
file_list = glob.glob("*.xml")
for fname in file_list:
    if fname not in exclude_list:
        stem = fname[0:-4]
        manvolnum, deps = extract_data(fname)
        deps = ":".join(deps) if deps else "None"
        output.append(",".join([stem, manvolnum, fname, deps]))

print(";".join(output))
