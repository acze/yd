.PHONY: test install build clean

# Run tests
test:
	python tests/test_yd.py

# Install in development mode
install:
	pip install -e .

# Build package
build:
	python -m build

# Clean build artifacts
clean:
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf __pycache__/
	rm -rf yd/__pycache__/
	rm -rf tests/__pycache__/

# Run a quick demo
demo:
	@echo "=== Basic diff demo ==="
	python yd/yamldiff.py tests/basic_old.yaml tests/basic_new.yaml
	@echo
	@echo "=== Environment variables demo ==="
	python yd/yamldiff.py tests/env_old.yaml tests/env_new.yaml
	@echo
	@echo "=== Counts demo ==="
	python yd/yamldiff.py --counts tests/basic_old.yaml tests/basic_new.yaml
