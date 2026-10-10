ARCH ?= x86_64
TARGET ?= $(ARCH)-linux-musl
PREFIX ?= $(CURDIR)/build/$(TARGET)
BUILD_DIR ?= $(CURDIR)/build/work/$(TARGET)
SOURCES_DIR ?= $(CURDIR)/sources
SOURCES_FILE ?= $(CURDIR)/sources.list

LLVM_MODE ?= system
JOBS ?= 2
LINK_JOBS ?= 1
HOST_CC ?= clang
HOST_CXX ?= clang++
TARGET_CFLAGS ?= -O2
HOST_CFLAGS ?=
HOST_CXXFLAGS ?=
HOST_LDFLAGS ?=
RUNNER ?=
