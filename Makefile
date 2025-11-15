IS_MAKE=1

include config.mk

all: build

pull:
	@if [ ! -d ./sources ]; then \
		echo "Sources Directory Not Found!"; \
		mkdir -p ./sources; \
		echo "Pulling Sources..."; \
		xargs -a ${SOURCES_FILE} -n1 -P4 -- curl -f -L -S -O --output-dir ./sources || { echo "curl failed"; exit 1; }; \
		echo "done"; \
	else \
		./scripts/check.sh; \
	fi

build: init
	./scripts/musl-cross.sh
	./scripts/elftoolchain-cross.sh

init:
	@if [ ! -d ./build/${FROOT} ]; then \
		@echo "Making toolchain directory..."; \
        	mkdir -p ./build/${FROOT}; \
		@echo "Making cross directory"; \
		mkdir -p ./build/cross; \
	fi
	@echo "updating configuration based on config.mk..."
	cp -r config.mk ./scripts/config.sh
	sed -i 's/shell //g' ./scripts/config.sh 

clean:
	rm -rf ./sources
	rm -rf ./build

help:
	@echo "musllvm"
	@echo "-----------------------"
	@echo "commands:"
	@echo "	all - make all (duh)"
	@echo "	pull - pull all sources (on first run), second run will check indivdually"
	@echo "	build - build will build to toolchain"
	@echo "	clean - clean up all sources and build artifacts"
	@echo "	init - sets up everything, run also every time you make changes to config.mk"
	@echo "	help - shows this menu"

.PHONY: all pull build clean init help
