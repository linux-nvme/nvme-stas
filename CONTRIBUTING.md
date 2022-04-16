# Coding style

nvme-stas uses [Black](https://black.readthedocs.io/en/stable/), pylint, and pyflakes to check the coding style. However, we do not necessarily agree 100% with these tools and we may ignore some of their recommendations especially if it will make the code harder to read (e.g. vertical alignment). 

With pylint its fairly easy to indicate which lines of code we do not want to be linted. With Black, however, it's not that easy. We can only control Black options at the command-line (see below) . And since we can't tell Black to disregard specific lines in the code, we can only do a visual inspection of the changes and accept or reject them. For that reason Black is only used manually with the following options:

```bash
black --line-length 200 --skip-string-normalization [file or directory]
```

# Minimum Python version required

nvme-stas must be able to run with Python 3.6. Code changes cannot use Python features not supported by Python 3.6. The only exception is for Python scripts used during the build phase (e.g. scripts to generate the documentation) or test scripts. Those scripts can follow Python 3.8 syntax.

nvme-stas use [vermin](https://pypi.org/project/vermin/) to verify that the code submitted complies with the minimum version required. Vermin gets executed as part of the tests (see `make test` below).

# Submitting changes

Always run the tests before submitting changes.

```bash
make test
```

This command not only runs the unit tests, but also pylint, pyflakes, and vermin. Obviously, these programs must be installed.
