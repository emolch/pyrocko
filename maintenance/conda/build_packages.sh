#!/bin/bash

set -e

if [ ! -f "build_packages.sh" ] ; then
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

if [ "$ACTION" == "UPLOAD" ] ; then
    if [ -z "$CONDA_USERNAME" -o -z "$CONDA_PASSWORD" ] ; then
        echo "need anaconda credentials as env variables"
        exit 1
    fi
fi

ORIGPATH="$PATH"

CONDA_URL="https://repo.anaconda.com/miniconda"
CONDA_PREFIX="/tmp/miniconda3"
CONDA_INSTALLER="miniconda3.sh"

export PATH="$CONDA_PREFIX/bin:$ORIGPATH"

if [ `uname` == "Darwin" ]; then
    CONDA_FILE="Miniconda3-latest-MacOSX-x86_64.sh"
else
    CONDA_FILE="Miniconda3-latest-Linux-x86_64.sh"
fi

# Install Miniconda

HERE=`pwd`
cd "$HOME"

if [ ! -f "$CONDA_INSTALLER" ] ; then
    echo "getting conda from:" "$CONDA_URL/$CONDA_FILE"
    curl "$CONDA_URL/$CONDA_FILE" -o "$CONDA_INSTALLER"
    chmod +x "$CONDA_INSTALLER"
    rm -rf "$CONDA_PREFIX"
fi

if [ ! -d "$CONDA_PREFIX" ] ; then
    "./$CONDA_INSTALLER" -b -u -p "$CONDA_PREFIX"
    conda install -y conda-build conda-verify anaconda-client numpy
fi

cd "$HERE"

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
