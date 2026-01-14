# Contributing guidelines

Thanks for contributing to this project. We'd like to get your feedback and suggestions.

## Issues

Bugs, feature requests, or issues must be reported through GitHub's "[Issues](https://github.com/linux-nvme/nvme-stas/issues)". Make sure there is not an existing open issue (or recently closed) for the same problem or feature. Include all pertinent info: environment, nvme-stas version, how to reproduce, expected result, etc.

## Contribution process

All contributions should be made through pull requests. Before submitting make sure that you followed the coding style (below) and you ran and passed the unit tests.

### How to submit contributions

1. Fork the repo
2. Make changes. Try to split you changes into distinct commits and avoid making big reformatting as it makes it harder to review the changes.
3. If possible, add unit tests for new features.
4. Run `make check-format` to make sure the changes conform to coding styles. See [Coding styles]() below.
5. Run `make test` and make sure all tests pass.
6. Commit to your fork with descriptive message and use the "`--signoff, -s`" option
7. Send the pull request
8. Check for failures in the automated CI output.
9. Be involved in the conversation (if any).

## Coding style

nvme-stas uses [ruff](https://docs.astral.sh/ruff/) to check that the code meets minimum style requirements. You can use this convenience make command:

```
make check-format
```

## Minimum Python version required

nvme-stas must be able to run with Python 3.6. Code changes cannot use Python features not supported by Python 3.6. The only exception is for Python scripts used during the build phase (e.g. scripts to generate the documentation) or test scripts. Those scripts can follow Python 3.8 syntax.

nvme-stas uses [vermin](https://pypi.org/project/vermin/) to verify that the code submitted complies with the minimum version required. Vermin gets executed as part of the tests (see `make test` below).

## Unit tests

Unit tests can be run with this command:

```bash
make test
```

This command not only runs the unit tests, but also pylint, pyflakes, and vermin. Make sure that these programs are installed otherwise the tests will be skipped.
