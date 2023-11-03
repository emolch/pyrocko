ARG base_image

FROM $base_image
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -y && apt-get upgrade -y

RUN apt-get install -y \
    python3-pip twine wget flake8 make git \
    python3-dev python3-setuptools python3-numpy-dev \
    xvfb libgles2-mesa-dev \
    python3-coverage python3-pytest \
    python3-numpy python3-scipy python3-matplotlib \
    python3-requests python3-future \
    python3-yaml \
    python3-pyqt5 python3-pyqt5.qtopengl python3-pyqt5.qtsvg \
    python3-pyqt5.qtwebengine python3-pyqt5.qtwebkit \
    python3-jinja2 python3-pybtex \
    python3-geojson python3-pyqtgraph python3-pyproj \
    gmt gmt-gshhg poppler-utils imagemagick \
    autoconf gfortran \
    && rm -f /usr/lib/python*/EXTERNALLY-MANAGED \
    && pip3 install --no-deps \
        utm git+https://github.com/pyrocko/kite

# sparrow test is extremely slow on debian 11, use pip vtk there:
ARG base_image
RUN [ "$base_image" = "debian:11" ] \
    && pip3 install vtk \
    || ( \
        apt-get install -y python3-vtk9 \
        || apt-get install -y python3-vtk8 \
        || apt-get install -y python3-vtk7 \
    )

# obspy does not work properly on debian-10 and ubuntu-20.04
ARG base_image
RUN [ "$base_image" != "debian:10" ] \
    && [ "$base_image" != "ubuntu:20.04" ] \
    && ( apt-get install -y \
        python3-sqlalchemy python3-lxml python3-greenlet \
    && pip3 install --no-deps obspy==1.3 || exit 1 ) || :

RUN mkdir -p /src \
    && cd /src && git clone https://git.pyrocko.org/pyrocko/fomosto-qseis.git \
    && cd fomosto-qseis && autoreconf -i && ./configure && make && make install \
    && cd /src && git clone https://git.pyrocko.org/pyrocko/fomosto-psgrn-pscmp.git \
    && cd fomosto-psgrn-pscmp && autoreconf -i && ./configure && make && make install \
    && cd /src && git clone https://git.pyrocko.org/pyrocko/fomosto-qseis2d.git \
    && cd fomosto-qseis2d && autoreconf -i && ./configure && make && make install \
    && cd /src && git clone https://git.pyrocko.org/pyrocko/fomosto-qssp.git \
    && cd fomosto-qssp && autoreconf -i && ./configure && make && make install \
    && cd /src && git clone https://git.pyrocko.org/pyrocko/fomosto-qssp2017.git \
    && cd fomosto-qssp2017 && autoreconf -i && ./configure && make && make install
