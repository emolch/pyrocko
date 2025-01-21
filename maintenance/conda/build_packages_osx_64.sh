#!/bin/bash

set -e

if [ ! -f "build_packages_osx_arm64.sh" ] ; then
    echo 'must be run from inside maintenance/conda'
    exit 1
fi

if [ ! -z "$(git status --untracked-files=no --porcelain)" ]; then
    echo "repos not clean"
    exit 1
fi


ACTION="$1"

if [ -z "$ACTION" ] ; then
    echo "usage: build_packages.sh (dryrun|upload)"
    exit 1
fi

if [ "$ACTION" == "upload" ] ; then
    if [ -z "$CONDA_USERNAME" -o -z "$CONDA_PASSWORD" ] ; then
        echo "need anaconda credentials as env variables"
        exit 1
    fi
fi

conda install -y conda-build conda-verify anaconda-client numpy

if [ "$ACTION" == "upload" ] ; then
    anaconda login --username "$CONDA_USERNAME" --password "$CONDA_PASSWORD" --hostname conda-builder-`uname`
    conda config --set anaconda_upload yes
    function anaconda_logout {
        anaconda logout
    }
    trap anaconda_logout EXIT
else
    conda config --set anaconda_upload no
fi

conda-build --python 3.8 --numpy 1.18 build
conda-build --python 3.9 --numpy 1.21 build
conda-build --python 3.10 --numpy 2.01 build
conda-build --python 3.11 --numpy 2.01 build
conda-build --python 3.12 --numpy 2.01 build
conda-build --python 3.13 --numpy 2.01 build

if [ "$ACTION" == "upload" ] ; then
    trap - EXIT
    anaconda_logout
fi
