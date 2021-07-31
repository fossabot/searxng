#!/usr/bin/env bash
# -*- coding: utf-8; mode: sh indent-tabs-mode: nil -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# shellcheck disable=SC2059,SC1117

if [[ -z "${REPO_ROOT}" ]]; then
    REPO_ROOT=$(dirname "${BASH_SOURCE[0]}")
    while [ -h "${REPO_ROOT}" ] ; do
        REPO_ROOT=$(readlink "${REPO_ROOT}")
    done
    REPO_ROOT=$(cd "${REPO_ROOT}/.." && pwd -P )
fi

required_commands() {

    # usage:  required_commands [cmd1 ...]

    local exit_val=0
    while [ -n "$1" ]; do

        if ! command -v "$1" &>/dev/null; then
            err_msg "missing command $1"
            exit_val=42
        fi
        shift
    done
    return $exit_val
}

# colors
# ------

# shellcheck disable=SC2034
set_terminal_colors() {
    # https://en.wikipedia.org/wiki/ANSI_escape_code

    # CSI (Control Sequence Introducer) sequences
    _show_cursor='\e[?25h'
    _hide_cursor='\e[?25l'

    # SGR (Select Graphic Rendition) parameters
    _creset='\e[0m'  # reset all attributes

    # original specification only had 8 colors
    _colors=8

    _Black='\e[0;30m'
    _White='\e[1;37m'
    _Red='\e[0;31m'
    _Green='\e[0;32m'
    _Yellow='\e[0;33m'
    _Blue='\e[0;94m'
    _Violet='\e[0;35m'
    _Cyan='\e[0;36m'

    _BBlack='\e[1;30m'
    _BWhite='\e[1;37m'
    _BRed='\e[1;31m'
    _BGreen='\e[1;32m'
    _BYellow='\e[1;33m'
    _BBlue='\e[1;94m'
    _BPurple='\e[1;35m'
    _BCyan='\e[1;36m'
}

if [ ! -p /dev/stdout ] && [ ! "$TERM" = 'dumb' ] && [ ! "$TERM" = 'unknown' ]; then
    set_terminal_colors
fi

# reST
# ----

die() {
    echo -e "${_BRed}ERROR:${_creset} ${BASH_SOURCE[1]}: line ${BASH_LINENO[0]}: ${2-died ${1-1}}" >&2;
    exit "${1-1}"
}

err_msg()  { echo -e "${_BRed}ERROR:${_creset} $*" >&2; }
warn_msg() { echo -e "${_BBlue}WARN:${_creset}  $*" >&2; }
info_msg() { echo -e "${_BYellow}INFO:${_creset}  $*" >&2; }

build_msg() {
    local tag="$1        "
    shift
    echo -e "${_Blue}${tag:0:10}${_creset}$*"
}

dump_return() {

    # Use this as last command in your function to prompt an ERROR message if
    # the exit code is not zero.

    local err=$1
    [ "$err" -ne "0" ] && err_msg "${FUNCNAME[1]} exit with error ($err)"
    return "$err"
}

clean_stdin() {
    if [[ $(uname -s) != 'Darwin' ]]; then
        while read -r -n1 -t 0.1; do : ; done
    fi
}

ask_yn() {
    # usage: ask_yn <prompt-text> [Ny|Yn] [<timeout in sec>]

    local EXIT_YES=0 # exit status 0 --> successful
    local EXIT_NO=1  # exit status 1 --> error code

    local _t=$3
    [[ -n $FORCE_TIMEOUT ]] && _t=$FORCE_TIMEOUT
    [[ -n $_t ]] && _t="-t $_t"
    case "${FORCE_SELECTION:-${2}}" in
        Y) return ${EXIT_YES} ;;
        N) return ${EXIT_NO} ;;
        Yn)
            local exit_val=${EXIT_YES}
            local choice="[${_BGreen}YES${_creset}/no]"
            local default="Yes"
            ;;
        *)
            local exit_val=${EXIT_NO}
            local choice="[${_BGreen}NO${_creset}/yes]"
            local default="No"
            ;;
    esac
    echo
    while true; do
        clean_stdin
        printf "$1 ${choice} "
        # shellcheck disable=SC2086
        read -r -n1 $_t
        if [[ -z $REPLY ]]; then
            printf "$default\n"; break
        elif [[ $REPLY =~ ^[Yy]$ ]]; then
            exit_val=${EXIT_YES}
            printf "\n"
            break
        elif [[ $REPLY =~ ^[Nn]$ ]]; then
            exit_val=${EXIT_NO}
            printf "\n"
            break
        fi
        _t=""
        err_msg "invalid choice"
    done
    clean_stdin
    return $exit_val
}

prefix_stdout () {
    # usage: <cmd> | prefix_stdout [prefix]

    local prefix="${_BYellow}-->|${_creset}"

    if [[ -n $1 ]] ; then prefix="$1"; fi

    # shellcheck disable=SC2162
    (while IFS= read line; do
        echo -e "${prefix}$line"
    done)
    # some piped commands hide the cursor, show cursory when the stream ends
    echo -en "$_show_cursor"
}


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

# folder where the python distribution takes place
PYDIST="${PYDIST:=dist}"

# folder where the intermediate build files take place
PYBUILD="${PYBUILD:=build/py${PY}}"

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

# Sphinx doc
# ----------

GH_PAGES="build/gh-pages"
DOCS_DIST="${DOCS_DIST:=dist/docs}"
DOCS_BUILD="${DOCS_BUILD:=build/docs}"

docs.html() {
    build_msg SPHINX "HTML ./docs --> file://$(readlink -e "$(pwd)/$DOCS_DIST")"
    pyenv.install
    docs.prebuild
    # shellcheck disable=SC2086
    PATH="${PY_ENV_BIN}:${PATH}" pyenv.cmd sphinx-build \
        ${SPHINX_VERBOSE} ${SPHINXOPTS} \
	-b html -c ./docs -d "${DOCS_BUILD}/.doctrees" ./docs "${DOCS_DIST}"
    dump_return $?
}

docs.live() {
    build_msg SPHINX  "autobuild ./docs --> file://$(readlink -e "$(pwd)/$DOCS_DIST")"
    pyenv.install
    docs.prebuild
    # shellcheck disable=SC2086
    PATH="${PY_ENV_BIN}:${PATH}" pyenv.cmd sphinx-autobuild \
        ${SPHINX_VERBOSE} ${SPHINXOPTS} --open-browser --host 0.0.0.0 \
	-b html -c ./docs -d "${DOCS_BUILD}/.doctrees" ./docs "${DOCS_DIST}"
    dump_return $?
}

docs.clean() {
    build_msg CLEAN "docs -- ${DOCS_BUILD} ${DOCS_DIST}"
    # shellcheck disable=SC2115
    rm -rf "${GH_PAGES}" "${DOCS_BUILD}" "${DOCS_DIST}"
    dump_return $?
}

# shellcheck disable=SC2155
docs.gh-pages() {

    # The commit history in the gh-pages branch makes no sense, the history only
    # inflates the repository unnecessarily.  Therefore a *new orphan* branch
    # is created each time we deploy on the gh-pages branch.

    docs.clean
    docs.prebuild
    docs.html

    [ "$VERBOSE" = "1" ] && set -x
    local head="$(git rev-parse HEAD)"
    local branch="$(git name-rev --name-only HEAD)"
    local remote="$(git config branch."${branch}".remote)"
    local remote_url="$(git config remote."${remote}".url)"

    build_msg GH-PAGES "prepare folder: ${GH_PAGES}"
    build_msg GH-PAGES "remote of the gh-pages branch: ${remote} / ${remote_url}"
    build_msg GH-PAGES "current branch: ${branch}"

    # prepare the *orphan* gh-pages working tree
    (
        git worktree remove -f "${GH_PAGES}"
        git branch -D gh-pages
    ) &> /dev/null  || true
    git worktree add --no-checkout "${GH_PAGES}" "${remote}/master"

    pushd "${GH_PAGES}" &> /dev/null
    git checkout --orphan gh-pages
    git rm -rfq .
    popd &> /dev/null

    cp -r "${DOCS_DIST}"/* "${GH_PAGES}"/
    touch "${GH_PAGES}/.nojekyll"
    cat > "${GH_PAGES}/404.html" <<EOF
<html><head><META http-equiv='refresh' content='0;URL=index.html'></head></html>
EOF

    pushd "${GH_PAGES}" &> /dev/null
    git add --all .
    git commit -q -m "gh-pages build from: ${branch}@${head} (${remote_url})"
    git push -f "${remote}" gh-pages
    popd &> /dev/null

    set +x
    build_msg GH-PAGES "deployed"
}
