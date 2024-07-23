#!/bin/sh

set -e

if [ ! -d libmseed ]; then
    rm -rf libmseed
    tar -xzf libmseed-2.19.6.tar.gz --exclude=doc --exclude=test --exclude=example
    patch -s -p0 < libmseed-2.19.6-speedread.patch
    patch -s -p0 < libmseed-2.19.6-selection-fallthru.patch
    patch -s -p0 < libmseed-2.19.6-fix-blkt-395-bswap.patch
fi

if [ ! -d evalresp-3.3.0 ]; then
    rm -rf evalresp-3.3.0
    tar -xzf evalresp-3.3.0.tar.gz
    patch -s -p0 < evalresp-3.3.0-fprintf-fmtstr.patch
    patch -s -p0 < evalresp-3.3.0-undef-complex.patch
fi
