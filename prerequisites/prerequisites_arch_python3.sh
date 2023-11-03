#!/bin/bash

sudo pacman -Syu --noconfirm --needed \
    git make gcc patch python python-setuptools python-pip python-wheel \
    python-numpy python-scipy python-matplotlib \
    python-pyqt5 python-pyqt5-webengine \
    python-cairo \
    python-requests python-yaml python-jinja \
    python-pytest python-coverage python-pyproj
