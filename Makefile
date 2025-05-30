

.PHONY: lint
lint:
	@pylint ./rplugin/python3/
	@flake8 .
