include config.mk

export ARCH TARGET PREFIX BUILD_DIR SOURCES_DIR SOURCES_FILE LLVM_MODE JOBS LINK_JOBS
export HOST_CC HOST_CXX TARGET_CFLAGS HOST_CFLAGS HOST_CXXFLAGS HOST_LDFLAGS RUNNER

all: build

build:
	sh scripts/build.sh all

pull:
	sh scripts/check.sh pull

verify-sources:
	sh scripts/check.sh verify

doctor:
	sh scripts/build.sh doctor

show-config:
	sh scripts/build.sh config

headers builtins musl atomic runtimes toolchain configure-llvm:
	sh scripts/build.sh $@

verify:
	sh scripts/verify.sh

check:
	sh scripts/test.sh

clean:
	sh scripts/build.sh clean

help:
	@printf '%s\n' \
	  'make [ARCH=x86_64|aarch64] [LLVM_MODE=system|source] [JOBS=2]' \
	  '  build           build and verify the complete cross toolchain (default)' \
	  '  doctor          check host dependencies' \
	  '  show-config     print paths and target configuration' \
	  '  pull            download and verify pinned source archives' \
	  '  verify-sources  check downloaded archives without network access' \
	  '  verify          compile, inspect, and optionally run C and C++ programs' \
	  '  check           run offline build-driver tests' \
	  '  clean           remove the selected toolchain and its work directory' \
	  '  configure-llvm  configure the optional LLVM source build'

.PHONY: all build pull verify-sources doctor show-config headers builtins musl
.PHONY: atomic runtimes toolchain configure-llvm verify check clean help
