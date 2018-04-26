# Shell to use with Make
SHELL := /bin/sh

# Set important variables
PROJECT := mail2mongo
PYTHON_BIN := $(VIRTUAL_ENV)/bin
REGISTRY := inn0kenty

VERSION := $(shell cat mail2mongo/__init__.py | grep "__version__" | awk '{print $$3}' | xargs)

PYINSTALLER_OPTIONS := \
		--noconfirm \
		--clean \
		--onefile \
		--name app \
		mail2mongo/__init__.py

clean:
	-rm -rf build dist *.spec

build_local:
	pyinstaller --paths $(VIRTUAL_ENV)/lib/python3.6/site-packages \
		$(PYINSTALLER_OPTIONS)

build:
	docker build --pull \
		--build-arg PYINSTALLER_ARG="$(PYINSTALLER_OPTIONS)" \
		-t $(REGISTRY)/$(PROJECT):latest \
		-t $(REGISTRY)/$(PROJECT):$(VERSION) .

push:
	docker push $(REGISTRY)/$(PROJECT):$(VERSION)
	docker push $(REGISTRY)/$(PROJECT):latest
