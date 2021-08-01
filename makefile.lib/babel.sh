# SPDX-License-Identifier: AGPL-3.0-or-later
# -*- coding: utf-8; mode: sh indent-tabs-mode: nil -*-

babel.compile() {
    build_msg BABEL compile
    pyenv.cmd pybabel compile -d "${REPO_ROOT}/searx/translations"
    dump_return $?
}
