#!/bin/sh

set -e

if [ ! -d libmseed ]; then
    rm -rf libmseed
    tar -xzf libmseed-2.19.6.tar.gz --exclude=doc --exclude=test --exclude=example
    patch -s -p0 < libmseed-2.19.6-speedread.patch
fi

if [ ! -d evalresp-3.3.0/lib ]; then
    rm -rf evalresp-3.3.0
    tar -xzf evalresp-3.3.0.tar.gz
    cd evalresp-3.3.0
    ./configure --prefix="`pwd`" --libdir="`pwd`/lib" CFLAGS=-fPIC
    make
    make install
    cd ..
fi

