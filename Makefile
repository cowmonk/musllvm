include config.mk

all: build

pull:
	@if [ ! -d ${PROOT}/sources ]; then \
		echo "Sources Directory Not Found!"; \
		mkdir -p ${PROOT}/sources; \
		echo "Pulling Sources..."; \
		xargs -a ${SOURCES_FILE} -n1 -P4 -- curl -f -L -S -O --output-dir ${PROOT}/sources || { echo "curl failed"; exit 1; }; \
		echo "Pulling cross musl compiler to build toolchain"
		curl -f -L -O https://musl.cc/${ARCH}-linux-musl-cross.tgz --output-dir ${PROOT}/sources
		echo "done"; \
	else \
		. ${PROOT}/scripts/check.sh; \
	fi

build: init
	. ${PROOT}/scripts/musl-cross.sh
	. ${PROOT}/scripts/elftoolchain-cross.sh

init:
	@if [ ! -d ./build/${FROOT} ]; then \
		echo "Making toolchain directory..."; \
        	mkdir -p ${PROOT}/build/${FROOT}; \
	fi
	@echo "updating configuration based on config.mk..."
	cp -r config.mk ${PROOT}/scripts/config.sh
	sed -i 's/shell //g' ${PROOT}/scripts/config.sh 

clean:
	rm -rf ${PROOT}/sources
	rm -rf ${PROOT}/build

help:
	@echo "musllvm"
	@echo "-----------------------"
	@echo "commands:"
	@echo "	all - make all (duh)"
	@echo "	pull - pull all sources (on first run), second run will check individually"
	@echo "	build - build will build to toolchain"
	@echo "	clean - clean up all sources and build artifacts"
	@echo "	init - sets up everything, run also every time you make changes to config.mk"
	@echo "	help - shows this menu"

.PHONY: all pull build clean init help
