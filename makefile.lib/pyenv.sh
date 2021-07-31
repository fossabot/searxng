# SPDX-License-Identifier: AGPL-3.0-or-later
# -*- coding: utf-8; mode: sh indent-tabs-mode: nil -*-

# python
# ------

PY="${PY:=3}"
PYTHON="${PYTHON:=python$PY}"
PY_ENV="${PY_ENV:=local/py${PY}}"
PY_ENV_BIN="${PY_ENV}/bin"
PY_ENV_REQ="${PY_ENV_REQ:=${REPO_ROOT}/requirements*.txt}"

# List of python packages (folders) or modules (files) installed by command:
# pyenv.install
PYOBJECTS="${PYOBJECTS:=.}"

# https://www.python.org/dev/peps/pep-0508/#extras
#PY_SETUP_EXTRAS='[develop,test]'
PY_SETUP_EXTRAS="${PY_SETUP_EXTRAS:=[develop,test]}"

PIP_BOILERPLATE=( pip wheel setuptools )

# shellcheck disable=SC2120
pyenv() {

    # usage:  pyenv [vtenv_opts ...]
    #
    #   vtenv_opts: see 'pip install --help'
    #
    # Builds virtualenv with 'requirements*.txt' (PY_ENV_REQ) installed.  The
    # virtualenv will be reused by validating sha256sum of the requirement
    # files.

    required_commands \
        sha256sum "${PYTHON}" \
        || exit

    local pip_req=()

    if ! pyenv.OK > /dev/null; then
        rm -f "${PY_ENV}/${PY_ENV_REQ}.sha256"
        pyenv.drop > /dev/null
        build_msg PYENV "[virtualenv] installing ${PY_ENV_REQ} into ${PY_ENV}"

        "${PYTHON}" -m venv "$@" "${PY_ENV}"
        "${PY_ENV_BIN}/python" -m pip install -U "${PIP_BOILERPLATE[@]}"

        for i in ${PY_ENV_REQ}; do
            pip_req=( "${pip_req[@]}" "-r" "$i" )
        done

        (
            [ "$VERBOSE" = "1" ] && set -x
            # shellcheck disable=SC2086
            "${PY_ENV_BIN}/python" -m pip install "${pip_req[@]}" \
                && sha256sum ${PY_ENV_REQ} > "${PY_ENV}/requirements.sha256"
        )
    fi
    pyenv.OK
}

_pyenv_OK=''
pyenv.OK() {

    # probes if pyenv exists and runs the script from pyenv.check

    [ "$_pyenv_OK" == "OK" ] && return 0

    if [ ! -f "${PY_ENV_BIN}/python" ]; then
        build_msg PYENV "[virtualenv] missing ${PY_ENV_BIN}/python"
        return 1
    fi

    if [ ! -f "${PY_ENV}/requirements.sha256" ] \
        || ! sha256sum --check --status <"${PY_ENV}/requirements.sha256" 2>/dev/null; then
        build_msg PYENV "[virtualenv] requirements.sha256 failed"
        sed 's/^/          [virtualenv] - /' <"${PY_ENV}/requirements.sha256"
        return 1
    fi

    if [ "$VERBOSE" = "1" ]; then
        pyenv.check \
            | "${PY_ENV_BIN}/python" 2>&1 \
            | prefix_stdout "${_Blue}PYENV     ${_creset}[check] "
    else
        pyenv.check | "${PY_ENV_BIN}/python" 1>/dev/null
    fi

    local err=${PIPESTATUS[1]}
    if [ "$err" -ne "0" ]; then
        build_msg PYENV "[check] python test failed"
        return "$err"
    fi

    [ "$VERBOSE" = "1" ] && build_msg PYENV "OK"
    _pyenv_OK="OK"
    return 0
}

pyenv.drop() {

    build_msg PYENV "[virtualenv] drop ${PY_ENV}"
    rm -rf "${PY_ENV}"
    _pyenv_OK=''

}

_pyenv_install_OK=''
pyenv.install.OK() {

    [ "$_pyenv_install_OK" == "OK" ] && return 0

    local imp=""
    local err=""

    if [ "." = "${PYOBJECTS}" ]; then
        imp="import $(basename "$(pwd)")"
    else
        # shellcheck disable=SC2086
        for i in ${PYOBJECTS}; do imp="$imp, $i"; done
        imp="import ${imp#,*} "
    fi
    (
        [ "$VERBOSE" = "1" ] && set -x
        "${PY_ENV_BIN}/python" -c "import sys; sys.path.pop(0); $imp;" 2>/dev/null
    )

    err=$?
    if [ "$err" -ne "0" ]; then
        build_msg PYENV "[install] python installation test failed"
        return "$err"
    fi

    build_msg PYENV "[install] OK"
    _pyenv_install_OK="OK"
    return 0
}

pyenv.cmd() {
    pyenv.install
    (   set -e
        # shellcheck source=/dev/null
        source "${PY_ENV_BIN}/activate"
        [ "$VERBOSE" = "1" ] && set -x
        "$@"
    )
}

py.clean() {
    build_msg CLEAN pyenv
    (   set -e
        pyenv.drop
        [ "$VERBOSE" = "1" ] && set -x
        rm -rf "${PYDIST}" "${PYBUILD}" "${PY_ENV}" ./.tox ./*.egg-info
        find . -name '*.pyc' -exec rm -f {} +
        find . -name '*.pyo' -exec rm -f {} +
        find . -name __pycache__ -exec rm -rf {} +
    )
}

pyenv.check() {
    cat  <<EOF
import yaml
print('import yaml --> OK')
EOF
}

pyenv.install() {

    if ! pyenv.OK; then
        py.clean > /dev/null
    fi
    if pyenv.install.OK > /dev/null; then
        return 0
    fi

    (   set -e
        pyenv
        build_msg PYENV "[install] pip install -e 'searx${PY_SETUP_EXTRAS}'"
        "${PY_ENV_BIN}/python" -m pip install -e ".${PY_SETUP_EXTRAS}"
        buildenv
    )
    local exit_val=$?
    if [ ! $exit_val -eq 0 ]; then
        die 42 "error while pip install (${PY_ENV_BIN})"
    fi
}

pyenv.uninstall() {
    build_msg PYENV "[pyenv.uninstall] uninstall packages: ${PYOBJECTS}"
    pyenv.cmd python setup.py develop --uninstall 2>&1 \
        | prefix_stdout "${_Blue}PYENV     ${_creset}[pyenv.uninstall] "

}
