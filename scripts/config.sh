# musllvm default flags
# --------------------------------
# feel free to change these however you like
#

#
# these are shared between the Makefile and scripts
#
ARCH=$(uname -m)
PROOT=${PWD}
SOURCES_FILE=${PROOT}/sources.list
FROOT="${ARCH}-musllvm"
CROSS="${PROOT}/build/cross" # cross directory

# MAKEFLAGS to parse the amounto of cores used
MAKEFLAGS="-j$(nproc) -l$(nproc)"
