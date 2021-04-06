#!/bin/bash
docker build nest -t pyrocko-nest
docker build docs -t pyrocko-docs
docker build util -t pyrocko-util
docker build pyrocko -t pyrocko
