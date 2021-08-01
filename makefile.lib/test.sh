# SPDX-License-Identifier: AGPL-3.0-or-later
# -*- coding: utf-8; mode: sh indent-tabs-mode: nil -*-

PYLINT_SEARX_DISABLE_OPTION="\
I,C,R,\
W0105,W0212,W0511,W0603,W0613,W0621,W0702,W0703,W1401,\
E1136"
PYLINT_ADDITIONAL_BUILTINS_FOR_ENGINES="supported_languages,language_aliases"
PYLINT_OPTIONS="-m pylint -j 0 --rcfile .pylintrc"

GECKODRIVER_VERSION="v0.28.0"

pylint.FILES() {

    # List files tagged by comment:
    #
    #   # lint: pylint
    #
    # These py files are linted by test.pylint(), all other files are linted by
    # test.pep8()

    grep -l -r --include \*.py '^#[[:blank:]]*lint:[[:blank:]]*pylint' searx searx_extra tests
}

PYLINT_FILES=()
while IFS= read -r line; do
   PYLINT_FILES+=("$line")
done <<< "$(pylint.FILES)"

YAMLLINT_FILES=()
while IFS= read -r line; do
   YAMLLINT_FILES+=("$line")
done <<< "$(git ls-files './tests/*.yml' './searx/*.yml' './utils/templates/etc/searx/*.yml')"

# shellcheck disable=SC2119
gecko.driver() {
    pyenv.install

    build_msg INSTALL "gecko.driver"
    # run installation in a subprocess and activate pyenv
    (   set -e
        # shellcheck source=/dev/null
        source "${PY_ENV_BIN}/activate"

        # TODO : check the current geckodriver version
        geckodriver -V > /dev/null 2>&1 || NOTFOUND=1
        set +e
        if [ -z "$NOTFOUND" ]; then
            build_msg INSTALL "geckodriver already installed"
            return
        fi
        PLATFORM="$(python3 -c 'import platform; print(platform.system().lower(), platform.architecture()[0])')"
        case "$PLATFORM" in
            "linux 32bit" | "linux2 32bit") ARCH="linux32";;
            "linux 64bit" | "linux2 64bit") ARCH="linux64";;
            "windows 32 bit") ARCH="win32";;
            "windows 64 bit") ARCH="win64";;
            "mac 64bit") ARCH="macos";;
        esac
        GECKODRIVER_URL="https://github.com/mozilla/geckodriver/releases/download/$GECKODRIVER_VERSION/geckodriver-$GECKODRIVER_VERSION-$ARCH.tar.gz";

        build_msg GECKO "Installing ${PY_ENV_BIN}/geckodriver from $GECKODRIVER_URL"

        FILE="$(mktemp)"
        wget -qO "$FILE" -- "$GECKODRIVER_URL" && tar xz -C "${PY_ENV_BIN}" -f "$FILE" geckodriver
        rm -- "$FILE"
        chmod 755 -- "${PY_ENV_BIN}/geckodriver"
    )
    dump_return $?
}

test.yamllint() {
    build_msg TEST "[yamllint] \$YAMLLINT_FILES"
    pyenv.cmd yamllint --format parsable "${YAMLLINT_FILES[@]}"
}

test.pylint() {
    # shellcheck disable=SC2086
    (   set -e
        build_msg TEST "[pylint] \$PYLINT_FILES"
        pyenv.cmd python ${PYLINT_OPTIONS} ${PYLINT_VERBOSE} \
            "${PYLINT_FILES[@]}"

        build_msg TEST "[pylint] searx/engines"
        pyenv.cmd python ${PYLINT_OPTIONS} ${PYLINT_VERBOSE} \
            --disable="${PYLINT_SEARX_DISABLE_OPTION}" \
            --additional-builtins="${PYLINT_ADDITIONAL_BUILTINS_FOR_ENGINES}" \
            searx/engines

        build_msg TEST "[pylint] searx tests"
        pyenv.cmd python ${PYLINT_OPTIONS} ${PYLINT_VERBOSE} \
            --disable="${PYLINT_SEARX_DISABLE_OPTION}" \
	    --ignore=searx/engines \
	    searx tests
    )
    dump_return $?
}

test.pep8() {
    build_msg TEST 'pycodestyle (formerly pep8)'
    local _exclude=""
    printf -v _exclude '%s, ' "${PYLINT_FILES[@]}"
    pyenv.cmd pycodestyle \
              --exclude="searx/static, searx/languages.py, $_exclude " \
              --max-line-length=120 \
              --ignore "E117,E252,E402,E722,E741,W503,W504,W605" \
              searx tests
    dump_return $?
}

test.unit() {
    build_msg TEST 'tests/unit'
    pyenv.cmd python -m nose2 -s tests/unit
    dump_return $?
}

test.coverage() {
    build_msg TEST 'unit test coverage'
    (   set -e
        pyenv.cmd python -m nose2 -C --log-capture --with-coverage --coverage searx -s tests/unit
        pyenv.cmd coverage report
        pyenv.cmd coverage html
    )
    dump_return $?
}

test.robot() {
    build_msg TEST 'robot'
    gecko.driver
    PYTHONPATH=. pyenv.cmd python searx/testing.py robot
    dump_return $?
}

test.clean() {
    build_msg CLEAN  "test stuff"
    rm -rf geckodriver.log .coverage coverage/
    dump_return $?
}
