# SPDX-License-Identifier: AGPL-3.0-or-later
# -*- coding: utf-8; mode: sh indent-tabs-mode: nil -*-

node.env() {
    if ! required_commands npm; then
        info_msg "to install build tools use::"
        info_msg "   sudo -H ./utils/searx.sh install buildhost"
        die 1 "install needed build tools first"
    fi

    (   set -e

        build_msg INSTALL "searx/static/themes/oscar/package.json"
        npm --prefix searx/static/themes/oscar install

        build_msg INSTALL "searx/static/themes/simple/package.json"
        npm --prefix searx/static/themes/simple install
    )
    dump_return $?
}

node.clean() {
    if ! required_commands npm 2>/dev/null; then
        build_msg CLEAN "npm is not installed / ignore npm dependencies"
        return 0
    fi
    build_msg CLEAN "locally installed npm dependencies"
    (   set -e
        npm --prefix searx/static/themes/oscar run clean
        npm --prefix searx/static/themes/simple run clean
    )
    dump_return $?
}

pygments.less() {
    build_msg PYGMENTS "searx_extra/update/update_pygments.py"
    if ! pyenv.cmd python searx_extra/update/update_pygments.py; then
        build_msg PYGMENTS "building LESS files for pygments failed"
        return 1
    fi
    return 0
}

themes.oscar() {
    build_msg GRUNT "theme: oscar"
    npm --prefix searx/static/themes/oscar run build
    dump_return $?
}

themes.simple() {
    build_msg GRUNT "theme: simple"
    npm --prefix searx/static/themes/simple run build
    dump_return $?
}

themes.all() {
    (   set -e
        pygments.less
        node.env
        themes.oscar
        themes.simple
    )
    dump_return $?
}
