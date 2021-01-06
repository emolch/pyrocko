#!/bin/bash

cd $(dirname $0)

docker build nest -t pyrocko-nest
docker build gpu-nest -t pyrocko-gpu-nest
docker build docs -t pyrocko-docs
docker build aux -t pyrocko-aux
docker build pyrocko -t pyrocko
