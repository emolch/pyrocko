#!/bin/bash

set -e

branch="$1"
if [ -z "$branch" ]; then
    branch=master
fi

thetest="$2"
if [ -z "$thetest" ]; then
    thetest="test"
fi

sudo chown -R vagrant:staff /vagrant

ORIGPATH="$PATH"

cd "$HOME"

CONDA_URL="https://repo.anaconda.com/miniconda"
CONDA_PREFIX="$HOME/miniconda3"
CONDA_INSTALLER="miniconda3.sh"
export PATH="$CONDA_PREFIX/bin:$ORIGPATH"

CONDA_FILE="Miniconda3-latest-MacOSX-x86_64.sh"

# Install Miniconda

if [ ! -f "$CONDA_INSTALLER" ] ; then
    curl "$CONDA_URL/$CONDA_FILE" -o "$CONDA_INSTALLER";
    chmod +x "$CONDA_INSTALLER"
    rm -rf "$CONDA_PREFIX"
fi

if [ ! -d "$CONDA_PREFIX" ] ; then
    "./$CONDA_INSTALLER" -b -u -p "$CONDA_PREFIX"
fi

pyrockodir="pyrocko-$branch"
outfile="/vagrant/test-$branch.py3.out"

rm -f "$outfile"


if [ -e "$pyrockodir" ] ; then
    rm -rf "$pyrockodir"
fi
git clone -b $branch "/vagrant/pyrocko.git" "$pyrockodir"
cd "$pyrockodir"
ln -s "/vagrant/pyrocko-test-data" "test/data"
ln -s "/vagrant/example_run_dir" "test/example_run_dir"

conda install -y \
    numpy \
    setuptools \
    scipy \
    matplotlib \
    pyqt \
    pyyaml \
    requests \
    pyproj \
    jinja2 \
    pytest

python3 install.py deps conda --yes && \
    python3 install.py user --yes && \
    python3 -m pyrocko.print_version deps >> "$outfile" && \
    python3 -m pytest -v "$thetest" > >(tee -a "$outfile") 2> >(tee -a "$outfile" >&2) || \
    /usr/bin/true
