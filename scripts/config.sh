# musllvm default flags
# --------------------------------
# feel free to change these however you like
#

#
# these are shared between the Makefile and scripts
#
ARCH=$(uname -m)
SOURCES_FILE=./sources.list
FROOT="${ARCH}-musllvm"
CROSS="./build/cross" # cross directory

# MAKEFLAGS to parse the amounto of cores used
MAKEFLAGS="-j$(nproc) -l$(nproc)"
