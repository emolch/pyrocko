
:: "c:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvars64.bat"

tar -xzf libmseed-2.19.6.tar.gz
cd libmseed
nmake -f Makefile.win lib
