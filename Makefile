include config.mk

SOURCES_FILE=./sources.list
ARCH=$(shell uname -m)
FROOT="${ARCH}-musllvm"

all:

pull:
	@if [ ! -d ./sources ]; then \
		echo "Sources Directory Not Found!"; \
		mkdir -p ./sources; \
		echo "Pulling Sources..."; \
		xargs -a ${SOURCES_FILE} -n1 -P4 -- curl -L -S -O --output-dir ./sources || { echo "curl failed"; exit 1; }; \
		echo "done"; \
	else \
		./scripts/check.sh; \
	fi

build: init
	./scripts/headers.sh	

init:
	@if [ ! -d ./build/${FROOT} ]; then \
		echo "Making toolchain directory..."; \
        	mkdir -p ./build/${FROOT}; \
	fi

clean:
	rm -rf ./sources
	rm -rf ./build

.PHONY: all pull build clean init
