# SPDX-License-Identifier: AGPL-3.0-or-later
# -*- coding: utf-8; mode: sh indent-tabs-mode: nil -*-

docker.push() {
    docker.build push
}

docker.buildx() {
    docker.build buildx
}

# shellcheck disable=SC2119
docker.build() {
    pyenv.install

    local SEARX_GIT_VERSION
    local VERSION_GITCOMMIT
    local GITHUB_USER
    local SEARX_IMAGE_NAME
    local BUILD

    build_msg DOCKER build
    # run installation in a subprocess and activate pyenv

    # See https://www.shellcheck.net/wiki/SC1001 and others ..
    # shellcheck disable=SC2031,SC2230,SC2002,SC2236,SC2143,SC1001
    (   set -e
        # shellcheck source=/dev/null
        source "${PY_ENV_BIN}/activate"

        # Check if it is a git repository
        if [ ! -d .git ]; then
	    die 1 "This is not Git repository"
        fi
        if [ ! -x "$(which git)" ]; then
	    die 1 "git is not installed"
        fi

        if ! git remote get-url origin 2> /dev/null; then
	    die 1 "there is no remote origin"
        fi

        # This is a git repository
        git update-index -q --refresh
        pyenv.cmd python -m searx.version freeze
        eval "$(pyenv.cmd python -m searx.version)"

        # Get the last git commit id
        VERSION_GITCOMMIT=$(echo "$VERSION_STRING" | cut -d- -f3)
        build_msg DOCKER "Last commit : $VERSION_GITCOMMIT"

        # define the docker image name
        GITHUB_USER=$(echo "${GIT_URL}" | sed 's/.*github\.com\/\([^\/]*\).*/\1/')
        SEARX_IMAGE_NAME="${SEARX_IMAGE_NAME:-${GITHUB_USER:-searxng}/searxng}"

        BUILD="build"
        if [ "$1" = "buildx" ]; then
            # buildx includes the push option
            CACHE_TAG="${SEARX_IMAGE_NAME}:latest-build-cache"
            BUILD="buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 --push --cache-from=type=registry,ref=$CACHE_TAG --cache-to=type=registry,ref=$CACHE_TAG,mode=max"
            shift
        fi
        build_msg DOCKER "Build command: ${BUILD}"

        # build Docker image
        build_msg DOCKER "Building image ${SEARX_IMAGE_NAME}:${SEARX_GIT_VERSION}"
        # shellcheck disable=SC2086
        docker $BUILD \
         --build-arg BASE_IMAGE="${DEPENDENCIES_IMAGE_NAME}" \
         --build-arg GIT_URL="${GIT_URL}" \
         --build-arg SEARX_GIT_VERSION="${VERSION_STRING}" \
         --build-arg VERSION_GITCOMMIT="${VERSION_GITCOMMIT}" \
         --build-arg LABEL_DATE="$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
         --build-arg LABEL_VCS_REF="$(git rev-parse HEAD)" \
         --build-arg LABEL_VCS_URL="${GIT_URL}" \
         --build-arg TIMESTAMP_SETTINGS="$(git log -1 --format="%cd" --date=unix -- searx/settings.yml)" \
         --build-arg TIMESTAMP_UWSGI="$(git log -1 --format="%cd" --date=unix -- dockerfiles/uwsgi.ini)" \
         -t "${SEARX_IMAGE_NAME}:latest" -t "${SEARX_IMAGE_NAME}:${VERSION_STRING}" .

        if [ "$1" = "push" ]; then
	        docker push "${SEARX_IMAGE_NAME}:latest"
	        docker push "${SEARX_IMAGE_NAME}:${SEARX_GIT_VERSION}"
	    fi
    )
    dump_return $?
}
