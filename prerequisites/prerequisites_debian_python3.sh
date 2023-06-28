#!/bin/bash

sudo apt-get update -y
sudo apt-get install -y make git python3-dev python3-setuptools python3-pip \
    python3-wheel python3-numpy python3-numpy-dev python3-scipy \
    python3-matplotlib python3-pyqt5 python3-pyqt5.qtopengl \
    python3-pyqt5.qtsvg python3-pyqt5.qtwebkit python3-yaml \
    python3-jinja2 python3-requests python3-coverage \
    python3-pytest python3-pyqt5.qtwebengine
sudo apt-get install -y python3-vtk9 \
    || sudo apt-get install -y python3-vtk8 \
    || sudo apt-get install -y python3-vtk7
