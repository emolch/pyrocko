#!/bin/bash

set -e

branch="$1"
action="$2"

pyrockodir="pyrocko"

cd $HOME

if [ -e "$pyrockodir" ] ; then
    sudo rm -rf "$pyrockodir"
fi


git clone -b "$branch" /vagrant/pyrocko.git "$pyrockodir"
cd "$pyrockodir/maintenance/conda"

source /vagrant/env.sh
./build_packages.sh "$action"
