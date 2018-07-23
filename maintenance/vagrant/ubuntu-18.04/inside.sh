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

pyrockodir="pyrocko-$branch"
outfile_py3="/vagrant/test-$branch.py3.out"
outfile_py2="/vagrant/test-$branch.py2.out"

rm -f "$outfile_py3"
rm -f "$outfile_py2"

cd $HOME
sudo apt-get update -y
sudo apt-get upgrade -y
sudo apt-get install -y git python-setuptools python3-setuptools xvfb

if [ -e "$pyrockodir" ] ; then
    sudo rm -rf "$pyrockodir"
fi
git clone -b $branch "/vagrant/pyrocko.git" "$pyrockodir"
cd "$pyrockodir"
ln -s "/pyrocko-test-data" "test/data"

python3 setup.py install_prerequisites --force-yes && \
    sudo python3 setup.py install -f && \
    python3 -m pyrocko.print_version deps >> "$outfile_py3" && \
    xvfb-run -s '-screen 0 640x480x24' python3 -m nose "$thetest" > >(tee -a "$outfile_py3") 2> >(tee -a "$outfile_py3" >&2) || \
    /bin/true

python2 setup.py install_prerequisites --force-yes && \
    sudo python2 setup.py install -f && \
    python2 -m pyrocko.print_version deps >> "$outfile_py2" && \
    xvfb-run -s '-screen 0 640x480x24' python2 -m nose "$thetest" > >(tee -a "$outfile_py2") 2> >(tee -a "$outfile_py2" >&2) || \
    /bin/true
